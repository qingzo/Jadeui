"""
JadeUI Global Hotkey API

全局热键注册 (JadeView 2.x)。即使应用不在前台也能触发。

Example:
    from jadeui import HotKey

    @HotKey.register("Ctrl+Shift+A")
    def on_hotkey():
        print("hotkey triggered!")

    # 或直接传回调
    hid = HotKey.register("Alt+F1", lambda: print("F1"))
    HotKey.unregister(hid)
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Callable, Dict, Optional, Tuple

from .core import DLLManager
from .core.types import GenericWindowEventCallback

logger = logging.getLogger(__name__)

# Win32 RegisterHotKey 修饰键位掩码
_MODIFIERS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "super": 0x0008,
    "cmd": 0x0008,
    "meta": 0x0008,
}

# 常用按键 -> Windows 虚拟键码
_VK = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "tab": 0x09,
    "backspace": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "plus": 0xBB,
    "minus": 0xBD,
}


def _parse_combo(combo: str) -> Tuple[int, int]:
    """将 "Ctrl+Shift+A" 解析为 (modifiers, vk)。"""
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError(f"无效热键: {combo!r}")
    mods = 0
    key = None
    for p in parts:
        if p in _MODIFIERS:
            mods |= _MODIFIERS[p]
        else:
            key = p
    if key is None:
        raise ValueError(f"热键缺少主键: {combo!r}")

    if len(key) == 1 and key.isalpha():
        vk = ord(key.upper())
    elif len(key) == 1 and key.isdigit():
        vk = ord(key)
    elif key in _VK:
        vk = _VK[key]
    elif key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if not 1 <= n <= 24:
            raise ValueError(f"无效功能键: {key}")
        vk = 0x70 + (n - 1)  # VK_F1 = 0x70
    else:
        raise ValueError(f"无法识别的按键: {key!r} (来自 {combo!r})")
    return mods, vk


class HotKey:
    """全局热键管理（JadeView 2.x，类级单例状态）"""

    _registered: Dict[int, Tuple[str, Callable[[], None]]] = {}
    _callback_registered: bool = False
    _cb_ref = None  # 防 GC

    @staticmethod
    def _dll() -> DLLManager:
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()
        return dll

    @classmethod
    def register(cls, combo: str, callback: Optional[Callable[[], None]] = None):
        """注册全局热键

        既可作装饰器使用，也可直接传入回调。

        Args:
            combo: 组合键字符串，如 "Ctrl+Shift+A"、"Alt+F1"
            callback: 触发回调（无参）。省略时返回装饰器。

        Returns:
            传入 callback 时返回 hotkey_id (0 表示失败)；作装饰器时返回原函数。
        """
        if callback is None:

            def decorator(func: Callable[[], None]):
                cls.register(combo, func)
                return func

            return decorator

        dll = cls._dll()
        if not dll.has_function("register_global_hotkey"):
            logger.warning("register_global_hotkey 不可用，需要 JadeView 2.x")
            return 0

        mods, vk = _parse_combo(combo)
        cls._ensure_event_handler()
        hotkey_id = dll.register_global_hotkey(mods, vk)
        if hotkey_id:
            cls._registered[hotkey_id] = (combo, callback)
            logger.debug(f"已注册全局热键 {combo} -> id={hotkey_id}")
        else:
            logger.warning(f"注册全局热键失败: {combo}")
        return hotkey_id

    @classmethod
    def unregister(cls, hotkey_id: int) -> bool:
        """注销全局热键"""
        dll = cls._dll()
        if not dll.has_function("unregister_global_hotkey"):
            return False
        ok = dll.unregister_global_hotkey(hotkey_id) == 1
        cls._registered.pop(hotkey_id, None)
        return ok

    @classmethod
    def unregister_all(cls) -> None:
        """注销所有已注册热键"""
        for hid in list(cls._registered.keys()):
            cls.unregister(hid)

    @classmethod
    def _ensure_event_handler(cls) -> None:
        if cls._callback_registered:
            return
        dll = cls._dll()

        @GenericWindowEventCallback
        def _on_hotkey(window_id: int, data: bytes):
            cls._dispatch(data)

        cls._cb_ref = _on_hotkey
        dll.jade_on(b"global-hotkey", ctypes.cast(_on_hotkey, ctypes.c_void_p))
        cls._callback_registered = True

    @classmethod
    def _dispatch(cls, data: bytes) -> None:
        hotkey_id = None
        try:
            d = json.loads(data.decode("utf-8")) if data else {}
            if isinstance(d, dict):
                hotkey_id = d.get("id", d.get("hotkey_id", d.get("hotkeyId")))
        except (ValueError, UnicodeDecodeError):
            pass

        targets = []
        if hotkey_id is not None and hotkey_id in cls._registered:
            targets.append(cls._registered[hotkey_id][1])
        elif len(cls._registered) == 1:
            # 无法从 payload 识别 id 时，若只注册了一个则直接触发
            targets.append(next(iter(cls._registered.values()))[1])

        for cb in targets:
            try:
                cb()
            except Exception as e:
                logger.error(f"热键回调异常: {e}")
