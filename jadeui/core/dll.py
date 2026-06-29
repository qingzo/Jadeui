"""
JadeUI DLL Manager

Handles loading and function binding for the JadeView DLL.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional

from ..exceptions import DLLLoadError
from .types import (
    FileDialogParams,
    MessageBoxParams,
    NotificationParams,
    TrayMenuItemDesc,
    WebViewSettings,
    WebViewWindowOptions,
)

if TYPE_CHECKING:
    from ctypes import CDLL

logger = logging.getLogger(__name__)


class DLLManager:
    """Manager for JadeView DLL loading and function binding

    Handles automatic discovery, loading, and function binding for the
    JadeView DLL. Functions that don't exist in the DLL are gracefully
    handled with stub implementations.
    """

    # Singleton instance
    _instance: Optional["DLLManager"] = None

    def __new__(cls, dll_path: Optional[str] = None) -> "DLLManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_instance(dll_path)
        return cls._instance

    def _init_instance(self, dll_path: Optional[str] = None) -> None:
        """Initialize instance attributes"""
        self.dll_path = dll_path or self._find_dll()
        self.dll: Optional["CDLL"] = None
        self._loaded = False
        self._available_functions: set[str] = set()
        self._unavailable_functions: set[str] = set()

    def __init__(self, dll_path: Optional[str] = None):
        # __init__ is called after __new__, but we already initialized in _init_instance
        pass

    def _find_dll(self) -> str:
        """Find the JadeView DLL in common locations

        If DLL is not found, attempts to download it automatically.
        """
        from ..downloader import (
            ensure_dll,
            find_dll,
            get_architecture,
            get_dist_dir_name,
            get_dll_filename,
        )

        # Try to find existing DLL
        dll_path = find_dll()
        if dll_path:
            return str(dll_path)

        # Current naming convention
        arch = get_architecture()
        dist_dir = get_dist_dir_name(arch)
        dll_name = get_dll_filename(arch)

        # Try PyInstaller/Nuitka paths
        try:
            base_path = sys._MEIPASS  # type: ignore
            meipass_paths = [
                Path(base_path) / dist_dir / dll_name,
                Path(base_path) / "lib" / dist_dir / dll_name,
            ]
            for path in meipass_paths:
                if path.exists():
                    return str(path)
        except AttributeError:
            pass

        # DLL not found - attempt to download
        try:
            dll_path = ensure_dll()
            return str(dll_path)
        except Exception as e:
            logger.error(f"Failed to ensure DLL: {e}")
            # Return default path (will fail later with better error message)
            return str(Path(__file__).parent.parent / "dll" / dist_dir / dll_name)

    def load(self) -> None:
        """Load the DLL and bind functions"""
        if self._loaded:
            return

        if not os.path.exists(self.dll_path):
            raise DLLLoadError(f"DLL not found at: {self.dll_path}")

        try:
            # 使用 WinDLL (stdcall) - JadeView DLL 使用 stdcall 调用约定
            if sys.platform == "win32":
                self.dll = ctypes.WinDLL(self.dll_path)
            else:
                self.dll = ctypes.CDLL(self.dll_path)
            self._bind_functions()
            self._loaded = True
            logger.info(f"DLL loaded from: {self.dll_path}")
            if self._unavailable_functions:
                logger.debug(
                    f"Unavailable functions: {', '.join(sorted(self._unavailable_functions))}"
                )
        except DLLLoadError:
            raise
        except Exception as e:
            raise DLLLoadError(f"Failed to load DLL: {e}")

    def _try_bind(
        self,
        name: str,
        argtypes: List[Any],
        restype: Any,
        required: bool = False,
    ) -> bool:
        """Try to bind a function from the DLL

        Args:
            name: Function name
            argtypes: Argument types
            restype: Return type
            required: If True, raise error if function not found

        Returns:
            True if function was bound successfully
        """
        assert self.dll is not None

        try:
            func = getattr(self.dll, name)
            func.argtypes = argtypes
            func.restype = restype
            self._available_functions.add(name)
            return True
        except AttributeError:
            if required:
                raise DLLLoadError(f"Required function '{name}' not found in DLL")
            self._unavailable_functions.add(name)
            return False

    def _bind_functions(self) -> None:
        """Bind all DLL functions with proper signatures"""
        dll = self.dll
        assert dll is not None, "DLL must be loaded before binding functions"

        # ==================== Required Functions ====================
        # These must exist for the SDK to work

        # Initialization (JadeView 2.x: 6 个参数)
        # JadeView_init(enable_devmod, log_path, data_directory,
        #               app_name, app_signature, single_instance)
        self._try_bind(
            "JadeView_init",
            [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_char_p,
                ctypes.c_int,
            ],
            ctypes.c_int,
            required=True,
        )

        # Event handling (v1.0+ jade_on returns callback_id)
        self._try_bind(
            "jade_on",
            [ctypes.c_char_p, ctypes.c_void_p],
            ctypes.c_uint32,  # Returns callback_id for jade_off
            required=True,
        )

        # Message loop
        self._try_bind("run_message_loop", [], None, required=True)

        # Cleanup / exit (JadeView 2.x: 推荐 jadeview_exit, cleanup_all_windows 已废弃)
        self._try_bind("jadeview_exit", [], ctypes.c_int)
        self._try_bind("cleanup_all_windows", [], ctypes.c_int)

        # Window management
        self._try_bind(
            "create_webview_window",
            [
                ctypes.c_char_p,
                ctypes.c_uint32,
                ctypes.POINTER(WebViewWindowOptions),
                ctypes.POINTER(WebViewSettings),
            ],
            ctypes.c_uint32,
            required=True,
        )

        self._try_bind("close_window", [ctypes.c_uint32], ctypes.c_int, required=True)

        # Deprecated: set_window_event_handlers will be removed in JadeView 0.2.1
        # Use jade_on as replacement. Keep for backward compatibility with older DLLs.
        self._try_bind(
            "set_window_event_handlers",
            [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
            ctypes.c_int,
        )

        # ==================== Optional Functions ====================
        # These are optional and the SDK will work without them

        self._try_bind("get_window_count", [], ctypes.c_uint32)

        # Window operations
        self._try_bind("minimize_window", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("toggle_maximize_window", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("set_window_theme", [ctypes.c_uint32, ctypes.c_char_p], ctypes.c_int)
        self._try_bind("set_window_backdrop", [ctypes.c_uint32, ctypes.c_char_p], ctypes.c_int)

        # Local server (JadeView 2.x: create_local_server 改名 set_protocol_service_path,
        # 去掉 appname，新增 hot_reload 参数)
        self._try_bind(
            "set_protocol_service_path",
            [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int],
            ctypes.c_int,
        )

        # IPC
        self._try_bind(
            "register_ipc_handler",
            [ctypes.c_char_p, ctypes.c_void_p],
            ctypes.c_int,
        )
        self._try_bind(
            "send_ipc_message",
            [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p],
            ctypes.c_int,
        )

        # Additional window properties
        self._try_bind(
            "set_window_title",
            [ctypes.c_uint32, ctypes.c_char_p],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_size",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_position",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_visible",
            [ctypes.c_uint32, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_always_on_top",
            [ctypes.c_uint32, ctypes.c_int],
            ctypes.c_int,
        )
        # get_window_theme(window_id) -> int (1=Dark, 0=Light)
        self._try_bind(
            "get_window_theme",
            [ctypes.c_uint32],
            ctypes.c_int,
        )

        # WebView navigation (JadeView 2.x: navigate_to_url 新增 headers_json 参数)
        self._try_bind(
            "navigate_to_url",
            [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p],
            ctypes.c_int,
        )
        self._try_bind(
            "execute_javascript",
            [ctypes.c_uint32, ctypes.c_char_p],
            ctypes.c_int,
        )
        # 刷新页面（正确函数名为 reload_webview_window）
        self._try_bind(
            "reload_webview_window",
            [ctypes.c_uint32],
            ctypes.c_int,
        )

        # Event system (v1.0+ jade_off requires callback_id)
        self._try_bind(
            "jade_off",
            [ctypes.c_char_p, ctypes.c_uint32],  # event_name, callback_id
            ctypes.c_int,
        )

        # Memory management tools (v1.2.0+)
        # jade_text_create: Create a safe text pointer for callback return values
        # 注意: restype 必须是 c_void_p，不能是 c_char_p，否则 ctypes 会自动转换为 bytes
        self._try_bind(
            "jade_text_create",
            [ctypes.c_char_p],
            ctypes.c_void_p,  # Returns void* pointer (不能用 c_char_p!)
        )
        # jade_text_free: Free a text pointer created by jade_text_create
        self._try_bind(
            "jade_text_free",
            [ctypes.c_char_p],
            None,
        )

        # Window state queries
        self._try_bind("is_window_maximized", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("is_window_minimized", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("is_window_visible", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("is_window_focused", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("is_window_fullscreen", [ctypes.c_uint32], ctypes.c_int)

        # Window focus (正确函数名为 set_window_focus)
        self._try_bind("set_window_focus", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind(
            "set_window_fullscreen",
            [ctypes.c_uint32, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_resizable",
            [ctypes.c_uint32, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_min_size",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_int],
            ctypes.c_int,
        )
        self._try_bind(
            "set_window_max_size",
            [ctypes.c_uint32, ctypes.c_int, ctypes.c_int],
            ctypes.c_int,
        )

        # WebView info
        self._try_bind(
            "get_webview_version",
            [ctypes.c_char_p, ctypes.c_size_t],
            ctypes.c_int,
        )

        # ==================== New in JadeView 2.x ====================
        # 动态内容保护、缩放、重绘、启用/禁用窗口
        self._try_bind("set_content_protection", [ctypes.c_uint32, ctypes.c_int], ctypes.c_int)
        self._try_bind("set_webview_zoom", [ctypes.c_uint32, ctypes.c_double], ctypes.c_int)
        self._try_bind("request_redraw", [ctypes.c_uint32], ctypes.c_int)
        self._try_bind("set_window_enabled", [ctypes.c_uint32, ctypes.c_int], ctypes.c_int)
        self._try_bind(
            "set_window_background_color", [ctypes.c_uint32, ctypes.c_char_p], ctypes.c_int
        )
        self._try_bind("set_window_frame_style", [ctypes.c_uint32, ctypes.c_char_p], ctypes.c_int)
        # 系统信息 / 版本
        self._try_bind("is_windows_11", [], ctypes.c_int)
        self._try_bind("jadeview_version", [ctypes.c_char_p, ctypes.c_size_t], ctypes.c_int)
        self._try_bind("get_webview_url", [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_int], ctypes.c_int)

        # ==================== Dialog API (JadeView 2.x) ====================
        # 参考: https://jade.run/docs/api
        # 同步函数返回 char*（结果 JSON 字符串，需 jade_text_free 释放）。
        # restype 用 c_void_p 以便手动读取并释放，避免 ctypes 自动转 bytes 丢失指针。

        # char* jade_dialog_show_open_dialog(const FileDialogParams* params);
        self._try_bind(
            "jade_dialog_show_open_dialog",
            [ctypes.POINTER(FileDialogParams)],
            ctypes.c_void_p,
        )
        # char* jade_dialog_show_save_dialog(const FileDialogParams* params);
        self._try_bind(
            "jade_dialog_show_save_dialog",
            [ctypes.POINTER(FileDialogParams)],
            ctypes.c_void_p,
        )
        # char* jade_dialog_show_message_box(const MessageBoxParams* params);
        self._try_bind(
            "jade_dialog_show_message_box",
            [ctypes.POINTER(MessageBoxParams)],
            ctypes.c_void_p,
        )

        # 异步变体: int fn(const Params* params, void(*callback)(const char*));
        self._try_bind(
            "jade_dialog_show_open_dialog_async",
            [ctypes.POINTER(FileDialogParams), ctypes.c_void_p],
            ctypes.c_int,
        )
        self._try_bind(
            "jade_dialog_show_save_dialog_async",
            [ctypes.POINTER(FileDialogParams), ctypes.c_void_p],
            ctypes.c_int,
        )
        self._try_bind(
            "jade_dialog_show_message_box_async",
            [ctypes.POINTER(MessageBoxParams), ctypes.c_void_p],
            ctypes.c_int,
        )

        # 显示错误框（简化的消息框）
        # int jade_dialog_show_error_box(u32 window_id, const char* title, const char* content);
        self._try_bind(
            "jade_dialog_show_error_box",
            [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p],  # window_id, title, content
            ctypes.c_int,
        )

        # ==================== Notification API (v1.3.0+) ====================
        # 参考: https://jade.run/guides/notification

        # 注册通知应用到 Windows 注册表
        # int set_notification_app_registry(const char* app_name, const char* icon_path);
        self._try_bind(
            "set_notification_app_registry",
            [ctypes.c_char_p, ctypes.c_char_p],  # app_name, icon_path
            ctypes.c_int,  # 返回 1 成功，0 失败
        )

        # 显示桌面通知
        # int show_notification(const NotificationParams* params);
        self._try_bind(
            "show_notification",
            [ctypes.POINTER(NotificationParams)],
            ctypes.c_int,  # 返回 1 成功，0 失败
        )

        self._bind_p3_functions()

    def _bind_p3_functions(self) -> None:
        """Bind JadeView 2.x extended functions (tray/menu/hotkey/clipboard/...)"""
        u32 = ctypes.c_uint32
        i32 = ctypes.c_int
        cp = ctypes.c_char_p
        sz = ctypes.c_size_t

        # ---- System tray ----
        self._try_bind("tray_create", [], u32)
        self._try_bind("tray_destroy", [u32], i32)
        self._try_bind("tray_set_visible", [u32, i32], i32)
        self._try_bind("tray_set_tooltip", [u32, cp], i32)
        self._try_bind("tray_set_icon_from_file", [u32, cp], i32)
        self._try_bind(
            "tray_set_menu_items",
            [u32, ctypes.POINTER(TrayMenuItemDesc), u32],
            i32,
        )
        self._try_bind(
            "set_tray_icon_from_data",
            [u32, ctypes.POINTER(ctypes.c_uint8), u32],
            i32,
        )

        # ---- Native / context menu ----
        self._try_bind("jade_menu_item_create", [cp, i32, u32, i32], u32)
        self._try_bind("jade_menu_item_set_enabled", [u32, i32], i32)
        self._try_bind("jade_menu_item_set_checked", [u32, i32], i32)
        self._try_bind("jade_menu_item_destroy", [u32], i32)
        self._try_bind(
            "jade_set_context_menu_items",
            [u32, ctypes.POINTER(u32), i32],
            i32,
        )

        # ---- Global hotkeys ----
        self._try_bind("register_global_hotkey", [u32, u32], u32)
        self._try_bind("unregister_global_hotkey", [u32], i32)

        # ---- Clipboard ----
        self._try_bind("clipboard_read_text", [cp, i32], i32)
        self._try_bind("clipboard_write_text", [cp], i32)

        # ---- Window extras ----
        self._try_bind("get_window_hwnd", [u32], sz)
        self._try_bind("get_window_bounds", [u32, cp, i32], i32)
        self._try_bind("set_window_ignore_cursor_events", [u32, i32], i32)
        self._try_bind("set_window_progress", [u32, i32, i32], i32)
        self._try_bind("flash_window", [u32, u32], i32)
        self._try_bind("open_devtools", [u32], i32)
        self._try_bind("close_devtools", [u32], i32)
        self._try_bind("is_devtools_open", [u32], i32)
        self._try_bind("clear_browsing_data", [u32], i32)
        self._try_bind("show_about_dialog", [u32], i32)
        self._try_bind("set_titlebar_overlay_style", [u32, i32, cp, cp], i32)
        self._try_bind(
            "create_borderless_webview_window",
            [cp, ctypes.POINTER(WebViewSettings)],
            u32,
        )

        # ---- System info ----
        self._try_bind("get_displays_info", [cp, sz], i32)
        self._try_bind("getLocale", [cp, sz], i32)
        self._try_bind("getPath", [cp, cp, sz], i32)
        self._try_bind("get_cursor_position", [cp, i32], i32)
        self._try_bind("clear_data_directory", [cp], i32)

        # ---- Printing ----
        self._try_bind("jade_print", [u32], i32)
        self._try_bind("jade_print_dialog", [cp], i32)
        self._try_bind("jade_get_printer_list", [cp, i32], i32)

        # ---- URL scheme / file association ----
        self._try_bind("register_url_scheme", [cp], i32)
        self._try_bind("unregister_url_scheme", [cp], i32)
        self._try_bind("register_file_association", [cp, cp], i32)
        self._try_bind("unregister_file_association", [cp], i32)

        # ---- Secure resources (jade://) ----
        self._try_bind("register_resource", [cp, u32, u32, cp, sz], i32)
        self._try_bind("unregister_resource", [cp], i32)
        self._try_bind("clear_window_resources", [u32], i32)

    def is_loaded(self) -> bool:
        """Check if DLL is loaded"""
        return self._loaded

    def has_function(self, name: str) -> bool:
        """Check if a function is available in the DLL

        Args:
            name: Function name

        Returns:
            True if function is available
        """
        return name in self._available_functions

    def get_available_functions(self) -> set[str]:
        """Get set of available function names"""
        return self._available_functions.copy()

    def get_unavailable_functions(self) -> set[str]:
        """Get set of unavailable function names"""
        return self._unavailable_functions.copy()

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the DLL

        For unavailable functions, returns a no-op stub that logs a warning.
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        if self.dll is None:
            raise DLLLoadError("DLL not loaded. Call load() first.")

        # Check if function is unavailable
        if name in self._unavailable_functions:
            # Return a stub function
            def stub(*args, **kwargs):
                logger.debug(f"Called unavailable DLL function: {name}")
                return 0  # Return 0 for int functions, harmless for None

            return stub

        return getattr(self.dll, name)
