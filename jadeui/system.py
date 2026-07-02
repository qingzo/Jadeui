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

    @staticmethod
    def set_login_autostart(enable: bool = True, args: Optional[str] = None) -> bool:
        """启用或取消开机自启（JadeView 2.3+）。"""
        dll = _dll()
        if not dll.has_function("set_login_autostart"):
            logger.warning("set_login_autostart 不可用，需要 JadeView 2.3+")
            return False
        args_bytes = args.encode("utf-8") if args else None
        return dll.set_login_autostart(1 if enable else 0, args_bytes) == 1

    @staticmethod
    def get_login_autostart() -> bool:
        """查询是否已启用开机自启（JadeView 2.3+）。"""
        dll = _dll()
        if not dll.has_function("get_login_autostart"):
            return False
        return dll.get_login_autostart() == 1

    @staticmethod
    def get_file_icon(
        path: str,
        size: int = 48,
        window_id: int = 0,
        ttl_seconds: int = 0,
        buffer_size: int = 4096,
    ) -> Optional[str]:
        """提取文件/目录系统图标，返回 ``jade://`` 安全资源 URL（JadeView 2.3+）。"""
        dll = _dll()
        if not dll.has_function("get_file_icon"):
            logger.warning("get_file_icon 不可用，需要 JadeView 2.3+")
            return None
        buf = ctypes.create_string_buffer(buffer_size)
        result = dll.get_file_icon(
            path.encode("utf-8"),
            int(size),
            int(window_id),
            int(ttl_seconds),
            buf,
            buffer_size,
        )
        if result != 1:
            return None
        return buf.value.decode("utf-8", "replace")

    @staticmethod
    def ntp_now(server: Optional[str] = None) -> Optional[int]:
        """获取 NTP UTC 毫秒时间戳（JadeView 2.3+）。网络失败返回 ``None``。"""
        dll = _dll()
        if not dll.has_function("jade_ntp_now"):
            logger.warning("jade_ntp_now 不可用，需要 JadeView 2.3+")
            return None
        server_bytes = server.encode("utf-8") if server else None
        result = int(dll.jade_ntp_now(server_bytes))
        return result if result >= 0 else None
