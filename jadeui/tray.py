"""
JadeUI System Tray API

系统托盘图标与菜单 (JadeView 2.x)。

Example:
    from jadeui import Tray

    tray = Tray()
    tray.set_icon("C:/path/to/icon.ico")
    tray.set_tooltip("我的应用")
    tray.set_menu([
        {"key": "open", "label": "打开主界面", "on_click": lambda: print("open")},
        {"type": "separator", "key": "sep1"},
        {"key": "quit", "label": "退出", "dangerous": True, "on_click": lambda: print("quit")},
    ])
    tray.show()
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from .core import DLLManager
from .core.types import GenericWindowEventCallback, TrayMenuItemDesc

logger = logging.getLogger(__name__)

# item_type 取值
_TYPE_NORMAL = 0
_TYPE_SUBMENU = 1
_TYPE_DIVIDER = 2
_TYPE_GROUP = 3


class Tray:
    """系统托盘图标（JadeView 2.x）

    需要在 JadeView 初始化、消息循环运行后使用（通常在 app ready 之后创建）。
    """

    # tray-menu-command / tray-event 事件回调（全局注册一次）
    _event_registered: bool = False
    _cb_refs: List[Any] = []
    # tray_id -> Tray 实例，用于事件分发
    _instances: Dict[int, "Tray"] = {}

    def __init__(self) -> None:
        self._dll = DLLManager()
        if not self._dll.is_loaded():
            self._dll.load()

        if not self._dll.has_function("tray_create"):
            logger.warning("tray_create 不可用，需要 JadeView 2.x")
            self.id = 0
        else:
            self.id = int(self._dll.tray_create())

        # key -> 回调
        self._menu_callbacks: Dict[str, Callable[[], None]] = {}
        self._click_callback: Optional[Callable[[str], None]] = None

        if self.id:
            Tray._instances[self.id] = self
            self._ensure_event_handler()

    # ---------- 基本属性 ----------

    def set_tooltip(self, text: str) -> "Tray":
        """设置悬浮提示文本"""
        if self.id:
            self._dll.tray_set_tooltip(self.id, text.encode("utf-8"))
        return self

    def set_icon(self, icon_path: str) -> "Tray":
        """从文件设置托盘图标"""
        if self.id:
            self._dll.tray_set_icon_from_file(self.id, icon_path.encode("utf-8"))
        return self

    def set_icon_from_bytes(self, data: bytes) -> "Tray":
        """从内存字节设置托盘图标"""
        if self.id and self._dll.has_function("set_tray_icon_from_data"):
            arr = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
            self._dll.set_tray_icon_from_data(self.id, arr, len(data))
        return self

    def show(self) -> "Tray":
        """显示托盘图标"""
        if self.id:
            self._dll.tray_set_visible(self.id, 1)
        return self

    def hide(self) -> "Tray":
        """隐藏托盘图标"""
        if self.id:
            self._dll.tray_set_visible(self.id, 0)
        return self

    def destroy(self) -> None:
        """销毁托盘图标"""
        if self.id:
            self._dll.tray_destroy(self.id)
            Tray._instances.pop(self.id, None)
            self.id = 0

    def on_click(self, callback: Callable[[str], None]) -> "Tray":
        """设置托盘图标点击回调

        回调接收事件类型字符串（如 "left" / "right" / "double"，具体以底层为准）。
        """
        self._click_callback = callback
        return self

    # ---------- 菜单 ----------

    def set_menu(self, items: List[Dict[str, Any]]) -> "Tray":
        """设置托盘右键菜单

        items 为菜单项列表，每项支持的字段:
            - key (str): 唯一标识（必填；分隔线也需唯一 key）
            - label (str): 显示文本
            - type (str): "normal"(默认) / "separator" / "submenu" / "group"
            - disabled (bool): 是否禁用
            - dangerous (bool): 是否危险项（红色高亮）
            - on_click (callable): 点击回调（无参）
            - children (list): 子菜单项（type 自动视为 submenu）

        传入空列表清除菜单。
        """
        if not self.id:
            return self

        self._menu_callbacks.clear()
        flat: List[TrayMenuItemDesc] = []
        # 保存 bytes 引用，防止 c_char_p 指向被回收的内存
        self._keepalive: List[bytes] = []

        def _b(s: Optional[str]) -> Optional[bytes]:
            if s is None:
                return None
            data = s.encode("utf-8")
            self._keepalive.append(data)
            return data

        def walk(item_list: List[Dict[str, Any]], parent_key: Optional[str]) -> None:
            for it in item_list:
                key = it.get("key")
                if not key:
                    raise ValueError("托盘菜单项必须包含唯一的 'key'")
                children = it.get("children")
                t = it.get("type", "submenu" if children else "normal")
                item_type = {
                    "normal": _TYPE_NORMAL,
                    "submenu": _TYPE_SUBMENU,
                    "separator": _TYPE_DIVIDER,
                    "divider": _TYPE_DIVIDER,
                    "group": _TYPE_GROUP,
                }.get(t, _TYPE_NORMAL)

                flat.append(
                    TrayMenuItemDesc(
                        item_type=item_type,
                        key=_b(key),
                        label=_b(it.get("label")),
                        parent_key=_b(parent_key),
                        disabled=1 if it.get("disabled") else 0,
                        dangerous=1 if it.get("dangerous") else 0,
                    )
                )
                if it.get("on_click"):
                    self._menu_callbacks[key] = it["on_click"]
                if children:
                    walk(children, key)

        walk(items, None)

        arr = (TrayMenuItemDesc * len(flat))(*flat)
        self._dll.tray_set_menu_items(self.id, arr, len(flat))
        return self

    # ---------- 事件 ----------

    @classmethod
    def _ensure_event_handler(cls) -> None:
        if cls._event_registered:
            return
        dll = DLLManager()

        @GenericWindowEventCallback
        def _on_menu_cmd(window_id: int, data: bytes):
            cls._dispatch_menu(data)

        @GenericWindowEventCallback
        def _on_tray_event(window_id: int, data: bytes):
            cls._dispatch_click(data)

        cls._cb_refs.extend([_on_menu_cmd, _on_tray_event])
        dll.jade_on(b"tray-menu-command", ctypes.cast(_on_menu_cmd, ctypes.c_void_p))
        dll.jade_on(b"tray-event", ctypes.cast(_on_tray_event, ctypes.c_void_p))
        cls._event_registered = True

    @staticmethod
    def _parse(data: bytes) -> dict:
        try:
            d = json.loads(data.decode("utf-8")) if data else {}
            return d if isinstance(d, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    @classmethod
    def _dispatch_menu(cls, data: bytes) -> None:
        d = cls._parse(data)
        key = d.get("key") or d.get("command") or d.get("menu_key")
        tray_id = d.get("tray_id") or d.get("trayId")
        # 优先按 tray_id 定位实例，否则遍历所有实例查找该 key
        instances = (
            [cls._instances[tray_id]] if tray_id in cls._instances else list(cls._instances.values())
        )
        for inst in instances:
            cb = inst._menu_callbacks.get(key)
            if cb:
                try:
                    cb()
                except Exception as e:
                    logger.error(f"托盘菜单回调异常: {e}")
                return

    @classmethod
    def _dispatch_click(cls, data: bytes) -> None:
        d = cls._parse(data)
        tray_id = d.get("tray_id") or d.get("trayId")
        event = d.get("event") or d.get("type") or ""
        instances = (
            [cls._instances[tray_id]] if tray_id in cls._instances else list(cls._instances.values())
        )
        for inst in instances:
            if inst._click_callback:
                try:
                    inst._click_callback(event)
                except Exception as e:
                    logger.error(f"托盘点击回调异常: {e}")
