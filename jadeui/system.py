"""
JadeUI System Utilities

系统信息与平台相关工具 (JadeView 2.x)：显示器、语言、系统路径、光标位置、版本。

Example:
    from jadeui import System

    print(System.is_windows_11())
    print(System.locale())
    print(System.displays())
    print(System.get_path("desktop"))
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Any, List, Optional

from .core import DLLManager

logger = logging.getLogger(__name__)


def _dll() -> DLLManager:
    dll = DLLManager()
    if not dll.is_loaded():
        dll.load()
    return dll


def _read_into_buffer(fn_name: str, size: int = 8192) -> Optional[str]:
    """调用 ``fn(buffer, size)`` 形式的函数并返回字符串。"""
    dll = _dll()
    if not dll.has_function(fn_name):
        logger.warning(f"{fn_name} 不可用，需要 JadeView 2.x")
        return None
    buf = ctypes.create_string_buffer(size)
    result = getattr(dll, fn_name)(buf, size)
    if result <= 0:
        return None
    return buf.value.decode("utf-8", "replace")


class System:
    """系统信息工具（JadeView 2.x，静态方法）"""

    @staticmethod
    def is_windows_11() -> bool:
        """当前系统是否为 Windows 11"""
        dll = _dll()
        if not dll.has_function("is_windows_11"):
            return False
        return dll.is_windows_11() == 1

    @staticmethod
    def locale() -> Optional[str]:
        """系统语言（BCP 47，如 ``zh-CN``）"""
        return _read_into_buffer("getLocale", 64)

    @staticmethod
    def displays() -> List[dict]:
        """显示器信息列表

        每项含 bounds、work_area、scale_factor、dpi_x/y、is_primary。
        """
        text = _read_into_buffer("get_displays_info", 1 << 14)
        if not text:
            return []
        try:
            data = json.loads(text)
            return data if isinstance(data, list) else [data]
        except (ValueError, TypeError):
            return []

    @staticmethod
    def cursor_position() -> Optional[dict]:
        """当前鼠标光标位置"""
        text = _read_into_buffer("get_cursor_position", 256)
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def get_path(name: str, buffer_size: int = 4096) -> Optional[str]:
        """获取系统路径

        Args:
            name: 路径名称（如 "desktop"、"documents"、"appdata"、"temp" 等，
                  具体支持名称以 JadeView 文档为准）
        """
        dll = _dll()
        if not dll.has_function("getPath"):
            logger.warning("getPath 不可用，需要 JadeView 2.x")
            return None
        buf = ctypes.create_string_buffer(buffer_size)
        result = dll.getPath(name.encode("utf-8"), buf, buffer_size)
        if result <= 0:
            return None
        return buf.value.decode("utf-8", "replace")

    @staticmethod
    def webview_version() -> Optional[str]:
        """WebView2 运行时版本"""
        return _read_into_buffer("get_webview_version", 256)

    @staticmethod
    def jadeview_version() -> Optional[str]:
        """JadeView 原生 DLL 版本（语义版本 + 构建号）"""
        return _read_into_buffer("jadeview_version", 128)
