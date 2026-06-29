"""
JadeUI Native Menu / Context Menu API

原生菜单与右键菜单 (JadeView 2.x)。

.. warning::
    **实验性**：本模块按官方头文件的 ABI 正确封装，但在当前测试环境中
    ``jade_menu_item_create`` 始终返回 0（创建失败），疑似存在头文件未说明的
    运行时前置条件（官方文档为 JS 渲染页面，暂无法核对）。若你需要托盘菜单，
    请优先使用 :class:`jadeui.Tray.set_menu`（已验证可用）。本 API 保留以便后续
    在官方文档明确后启用。

Example (右键菜单):
    from jadeui import Menu, Window

    win = Window(title="Demo")

    Menu.attach_context_menu(win, [
        {"label": "刷新", "on_click": lambda: win.reload()},
        {"type": "separator"},
        {"label": "开发者工具", "on_click": lambda: win.open_devtools()},
        {"label": "更多", "children": [
            {"label": "关于", "on_click": lambda: print("about")},
        ]},
    ])
    win.run()
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

from .core import DLLManager
from .core.types import GenericWindowEventCallback

logger = logging.getLogger(__name__)

# jade_menu_item_create kind 取值
KIND_NORMAL = 0
KIND_SEPARATOR = 1
KIND_CHECKBOX = 2
KIND_RADIO = 3
KIND_SUBMENU = 4

_KIND_BY_NAME = {
    "normal": KIND_NORMAL,
    "separator": KIND_SEPARATOR,
    "divider": KIND_SEPARATOR,
    "checkbox": KIND_CHECKBOX,
    "radio": KIND_RADIO,
    "submenu": KIND_SUBMENU,
}


class Menu:
    """原生菜单管理（JadeView 2.x，类级状态）"""

    _callbacks: Dict[int, Callable[[], None]] = {}  # item_id -> 回调
    _window_menus: Dict[int, List[int]] = {}  # window_id -> 顶级 menu_id 列表
    _event_registered: bool = False
    _cb_refs: List[Any] = []
    _next_item_id: int = 1000

    @staticmethod
    def _dll() -> DLLManager:
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()
        return dll

    @classmethod
    def create_item(
        cls,
        label: str = "",
        on_click: Optional[Callable[[], None]] = None,
        kind: int = KIND_NORMAL,
        parent_menu_id: int = 0,
        enabled: bool = True,
        checked: bool = False,
    ) -> int:
        """创建一个菜单项，返回 menu_id (0=失败)

        Args:
            label: 显示文本
            on_click: 点击回调（无参）
            kind: KIND_NORMAL / KIND_SEPARATOR / KIND_CHECKBOX / KIND_RADIO / KIND_SUBMENU
            parent_menu_id: 0=顶级；>0=添加到指定子菜单
            enabled: 是否启用
            checked: 复选/单选是否选中

        Returns:
            menu_id（用于作为子菜单父项或加入右键菜单列表）
        """
        dll = cls._dll()
        if not dll.has_function("jade_menu_item_create"):
            logger.warning("jade_menu_item_create 不可用，需要 JadeView 2.x")
            return 0

        cls._next_item_id += 1
        item_id = cls._next_item_id
        menu_id = int(
            dll.jade_menu_item_create(label.encode("utf-8"), kind, parent_menu_id, item_id)
        )
        if not menu_id:
            return 0

        if on_click is not None:
            cls._callbacks[item_id] = on_click
            cls._ensure_event_handler()
        if not enabled:
            dll.jade_menu_item_set_enabled(menu_id, 0)
        if checked:
            dll.jade_menu_item_set_checked(menu_id, 1)
        return menu_id

    @classmethod
    def set_enabled(cls, menu_id: int, enabled: bool = True) -> bool:
        dll = cls._dll()
        return dll.jade_menu_item_set_enabled(menu_id, 1 if enabled else 0) == 1

    @classmethod
    def set_checked(cls, menu_id: int, checked: bool = True) -> bool:
        dll = cls._dll()
        return dll.jade_menu_item_set_checked(menu_id, 1 if checked else 0) == 1

    @classmethod
    def destroy(cls, menu_id: int) -> bool:
        dll = cls._dll()
        return dll.jade_menu_item_destroy(menu_id) == 1

    @classmethod
    def _build_items(cls, items: List[Dict[str, Any]], parent_menu_id: int = 0) -> List[int]:
        """递归构建菜单项，返回该层级的 menu_id 列表。"""
        ids: List[int] = []
        for it in items:
            children = it.get("children")
            t = it.get("type", "submenu" if children else "normal")
            kind = _KIND_BY_NAME.get(t, KIND_NORMAL)
            mid = cls.create_item(
                label=it.get("label", ""),
                on_click=it.get("on_click"),
                kind=kind,
                parent_menu_id=parent_menu_id,
                enabled=not it.get("disabled", False),
                checked=it.get("checked", False),
            )
            if children:
                cls._build_items(children, mid)
            ids.append(mid)
        return ids

    @classmethod
    def attach_context_menu(
        cls, window: Union[int, Any], items: List[Dict[str, Any]]
    ) -> List[int]:
        """为窗口绑定右键菜单

        在 ``context-menu`` 事件中自动用本菜单调用 jade_set_context_menu_items。

        Args:
            window: Window 实例或 window_id
            items: 菜单项列表，字段同 :func:`create_item`，支持 ``children`` 嵌套子菜单、
                   ``type="separator"`` 分隔线。

        Returns:
            顶级 menu_id 列表
        """
        window_id = getattr(window, "id", window) or 0
        top_ids = cls._build_items(items, 0)
        cls._window_menus[int(window_id)] = top_ids
        cls._ensure_event_handler()
        return top_ids

    @classmethod
    def show_context_menu(cls, window: Union[int, Any], menu_ids: List[int]) -> bool:
        """立即为窗口设置要显示的右键菜单项（在 context-menu 回调中调用）"""
        dll = cls._dll()
        if not dll.has_function("jade_set_context_menu_items"):
            return False
        window_id = int(getattr(window, "id", window) or 0)
        arr = (ctypes.c_uint32 * len(menu_ids))(*menu_ids)
        return dll.jade_set_context_menu_items(window_id, arr, len(menu_ids)) == 1

    # ---------- 事件 ----------

    @classmethod
    def _ensure_event_handler(cls) -> None:
        if cls._event_registered:
            return
        dll = cls._dll()

        @GenericWindowEventCallback
        def _on_clicked(window_id: int, data: bytes):
            cls._dispatch_click(data)

        @GenericWindowEventCallback
        def _on_context(window_id: int, data: bytes):
            cls._on_context_menu(window_id, data)

        cls._cb_refs.extend([_on_clicked, _on_context])
        dll.jade_on(b"menu-item-clicked", ctypes.cast(_on_clicked, ctypes.c_void_p))
        dll.jade_on(b"context-menu", ctypes.cast(_on_context, ctypes.c_void_p))
        cls._event_registered = True

    @staticmethod
    def _parse(data: bytes) -> dict:
        try:
            d = json.loads(data.decode("utf-8")) if data else {}
            return d if isinstance(d, dict) else {}
        except (ValueError, UnicodeDecodeError):
            return {}

    @classmethod
    def _dispatch_click(cls, data: bytes) -> None:
        d = cls._parse(data)
        item_id = d.get("item_id", d.get("itemId", d.get("id")))
        cb = cls._callbacks.get(item_id)
        if cb:
            try:
                cb()
            except Exception as e:
                logger.error(f"菜单回调异常: {e}")

    @classmethod
    def _on_context_menu(cls, window_id: int, data: bytes) -> None:
        # 在右键事件回调里设置该窗口注册过的菜单
        menu_ids = cls._window_menus.get(int(window_id))
        if menu_ids:
            cls.show_context_menu(window_id, menu_ids)
