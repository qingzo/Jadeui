"""
JadeUI Window

Window management for JadeUI applications.
"""

from __future__ import annotations

import ctypes
import logging
from json import loads as _json_loads
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from .core import DLLManager
from .core.types import (
    RGBA,
    FileDropCallback,
    GenericWindowEventCallback,
    WebViewSettings,
    WebViewWindowOptions,
    rgba_to_hex,
)
from .events import EventEmitter
from .exceptions import WindowCreationError

# Type variables for callback decorators
F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger(__name__)


# Theme constants
class Theme:
    """Window theme constants"""

    LIGHT = "Light"
    DARK = "Dark"
    SYSTEM = "System"


# Backdrop material constants (Windows 11)
class Backdrop:
    """Window backdrop material constants for Windows 11

    Note: Window must have transparent=True for backdrop effects to work.
    """

    MICA = "mica"  # Mica 效果，Windows 11 默认背景材料
    MICA_ALT = "micaAlt"  # Mica Alt 效果，Mica 的替代版本
    ACRYLIC = "acrylic"  # Acrylic 效果，半透明模糊背景


# ==================== Event Parameter Extractors ====================
# Pre-compiled extractors for high-performance event argument parsing.
# Format: event_name -> (extractor_func, is_dict_passthrough)
# - extractor_func: lambda that extracts args tuple from parsed JSON dict
# - is_dict_passthrough: if True, pass the entire dict to callback


def _extract_none(d: Dict) -> tuple:
    return ()


def _extract_resize(d: Dict) -> tuple:
    return (d.get("width", 0), d.get("height", 0))


def _extract_move(d: Dict) -> tuple:
    return (d.get("x", 0), d.get("y", 0))


def _extract_state(d: Dict) -> tuple:
    return (d.get("isMaximized", False),)


def _extract_fullscreen(d: Dict) -> tuple:
    return (d.get("fullscreen", False),)


def _extract_url(d: Dict) -> tuple:
    return (d.get("url", ""),)


def _extract_title(d: Dict) -> tuple:
    return (d.get("title", ""),)


def _extract_new_window(d: Dict) -> tuple:
    return (d.get("url", ""), d.get("frame_name", ""))


def _extract_favicon(d: Dict) -> tuple:
    return (d.get("favicon", ""),)


def _extract_js_result(d: Dict) -> tuple:
    return (d.get("callbackId"), d.get("result"))


def _extract_download(d: Dict) -> tuple:
    return (d.get("url", ""), d.get("filename", ""))


# Event extractors mapping: event_name -> (extractor, pass_dict_if_no_extractor)
_EVENT_EXTRACTORS: Dict[str, Callable[[Dict], tuple]] = {
    # Window events
    "window-resized": _extract_resize,
    "window-moved": _extract_move,
    "window-state-changed": _extract_state,
    "window-fullscreen": _extract_fullscreen,  # v1.2+
    "window-focused": _extract_none,
    "window-blurred": _extract_none,
    "window-closing": _extract_none,
    "window-created": _extract_none,
    "window-closed": _extract_none,
    "window-destroyed": _extract_none,
    # WebView events
    "webview-will-navigate": _extract_url,
    "webview-did-start-loading": _extract_url,
    "webview-did-finish-load": _extract_url,
    "webview-new-window": _extract_new_window,
    "webview-page-title-updated": _extract_title,
    "favicon-updated": _extract_favicon,
    "webview-page-favicon-updated": _extract_favicon,  # JadeView 2.x 名称
    "webview-download-started": _extract_download,  # v0.3.1+
    "webview-download-completed": _extract_download,  # JadeView 2.x 名称
    # Other events
    "javascript-result": _extract_js_result,
}


class Window(EventEmitter):
    """A WebView window in JadeUI

    Represents a single window containing a WebView. Windows can be created,
    configured, and controlled through this class.

    Example:
        window = Window(title="My App", width=1024, height=768)
        window.load_url("https://example.com")
        window.show()

    Events:
        - 'close': Fired when window is about to close
        - 'closed': Fired when window is closed
        - 'focus': Fired when window gains focus
        - 'blur': Fired when window loses focus
        - 'resize': Fired when window is resized
        - 'move': Fired when window is moved
        - 'page-loaded': Fired when page finishes loading
        - 'file-drop': Fired when files are dropped on window
                       Args: (files: List[str], x: float, y: float)
                       Note: 使用此事件会接管 WebView 的拖拽事件处理，
                             导致前端无法收到原生拖拽事件。
    """

    # Class-level window registry
    _windows: dict[int, "Window"] = {}

    # Class-level flag to track if global event handlers are registered
    _global_handlers_registered: bool = False
    # Class-level callback references to prevent garbage collection
    _global_callbacks: list = []

    def __init__(
        self,
        title: str = "Window",
        width: int = 800,
        height: int = 600,
        url: Optional[str] = None,
        dll_manager: Optional[DLLManager] = None,
        **options,
    ):
        """Create a new window

        Args:
            title: Window title
            width: Window width in pixels
            height: Window height in pixels
            url: URL to load (optional, can be set later)
            dll_manager: DLL manager instance (uses global if None)
            **options: Additional window options:
                - resizable (bool): Allow window resizing (default: True)
                - remove_titlebar (bool): Remove native title bar (default: False)
                - transparent (bool): Enable window transparency (default: False)
                - background_color (RGBA): Window background color
                - always_on_top (bool): Keep window always on top (default: False)
                - theme (str): Window theme ('Light', 'Dark', 'System')
                - maximized (bool): Start maximized (default: False)
                - maximizable (bool): Allow maximize (default: True)
                - minimizable (bool): Allow minimize (default: True)
                - x (int): Window X position (-1 for center)
                - y (int): Window Y position (-1 for center)
                - min_width (int): Minimum window width
                - min_height (int): Minimum window height
                - max_width (int): Maximum window width (0 for no limit)
                - max_height (int): Maximum window height (0 for no limit)
                - fullscreen (bool): Start in fullscreen (default: False)
                - focus (bool): Focus window on creation (default: True)
                - hide_window (bool): Create hidden (default: False)
                - use_page_icon (bool): Use page favicon as window icon (default: True)
                - autoplay (bool): Allow media autoplay (default: False)
                - disable_right_click (bool): Disable right-click menu (default: True)
                - user_agent (str): Custom user agent string
                - preload_js (str): JavaScript to run before page load
                - allow_fullscreen (bool): Allow page to enter fullscreen (default: True)
                    Note: Requires JadeView DLL 0.2.1+
                - postmessage_whitelist (str): PostMessage whitelist, comma-separated origins
                    Example: "https://example.com,https://another.com"
                    Note: Requires JadeView DLL 1.0.2+
        """
        super().__init__()

        self.dll_manager = dll_manager or DLLManager()
        if not self.dll_manager.is_loaded():
            self.dll_manager.load()

        self.id: Optional[int] = None
        self._title = title
        self._width = width
        self._height = height
        self._url = url

        # Store options for later use
        self._options = options.copy()
        self._options.setdefault("resizable", True)
        self._options.setdefault("remove_titlebar", False)
        self._options.setdefault("transparent", False)
        self._options.setdefault("background_color", RGBA(255, 255, 255, 255))
        self._options.setdefault("always_on_top", False)
        self._options.setdefault("theme", Theme.SYSTEM)
        self._options.setdefault("maximized", False)
        self._options.setdefault("maximizable", True)
        self._options.setdefault("minimizable", True)
        self._options.setdefault("x", -1)
        self._options.setdefault("y", -1)
        self._options.setdefault("min_width", 0)
        self._options.setdefault("min_height", 0)
        self._options.setdefault("max_width", 0)
        self._options.setdefault("max_height", 0)
        self._options.setdefault("fullscreen", False)
        self._options.setdefault("focus", True)
        self._options.setdefault("hide_window", False)
        self._options.setdefault("use_page_icon", True)
        self._options.setdefault("borderless", False)
        self._options.setdefault("frame_style", None)  # JadeView 2.x: 显式覆盖 titlebar/borderless
        self._options.setdefault("content_protection", False)
        self._options.setdefault("auto_save_state", False)  # JadeView 2.x: 自动保存窗口状态

        # 参数冲突检测：borderless 与 remove_titlebar/transparent 不能同时使用
        # 参考：JadeView DLL v1.2.0 已知问题
        if self._options.get("borderless"):
            conflicts = []
            if self._options.get("remove_titlebar"):
                conflicts.append("remove_titlebar")
            if self._options.get("transparent"):
                conflicts.append("transparent")
            if conflicts:
                raise ValueError(
                    f"参数冲突: 'borderless=True' 不能与 {', '.join(conflicts)} 同时使用。"
                    f"\n提示: borderless 会移除边框和系统阴影，与 remove_titlebar/transparent 功能冲突，"
                    f"可能导致 DLL 崩溃。请选择其中一种方式。"
                )

        # 参数冲突检测：content_protection 与 maximizable/minimizable 冲突
        # 参考：JadeView DLL 已知问题
        if self._options.get("content_protection"):
            conflicts = []
            if self._options.get("maximizable", True):  # 默认为 True
                conflicts.append("maximizable")
            if self._options.get("minimizable", True):  # 默认为 True
                conflicts.append("minimizable")
            if conflicts:
                raise ValueError(
                    f"参数冲突: 'content_protection=True' 不能与 {', '.join(conflicts)} 同时使用。"
                    f"\n提示: 启用内容保护时，请设置 maximizable=False 和 minimizable=False。"
                )

        # WebView settings
        self._options.setdefault("autoplay", False)
        self._options.setdefault("background_throttling", False)
        self._options.setdefault("disable_right_click", False)
        self._options.setdefault("user_agent", None)
        self._options.setdefault("preload_js", None)
        self._options.setdefault("allow_fullscreen", True)  # JadeView 0.2.1+

        # Callback references to prevent garbage collection
        self._callbacks: list = []

        # 通过 jade_on 注册的事件标志
        self._registered_jade_events: set[str] = set()

        # 待应用的设置（在窗口创建前设置的属性）
        self._pending_backdrop: Optional[str] = None

        # JavaScript 执行回调注册表: callbackId -> callback
        self._js_callbacks: Dict[int, Callable[[Any], Any]] = {}
        self._js_callback_id_counter: int = 0

    # 需要通过 jade_on 注册到 DLL 的事件列表
    # 参考: https://jade.run/guides/communication-api
    JADE_ON_EVENTS = {
        # 窗口事件
        "window-resized",  # {"width": 宽度, "height": 高度}
        "window-moved",  # {"x": x坐标, "y": y坐标}
        "window-state-changed",  # {"isMaximized": 布尔值}
        "window-fullscreen",  # {"fullscreen": 布尔值} (v1.2+)
        "window-focused",  # {}
        "window-blurred",  # {}
        "window-closing",  # {} - 可返回 "1" 阻止关闭
        "window-created",  # {}
        "window-closed",  # {}
        "window-destroyed",  # {}
        "resized",  # "宽度,高度" (旧兼容格式)
        # WebView 事件
        "webview-will-navigate",  # {"url": "目标URL", "window_id": 窗口ID}
        "webview-did-start-loading",  # {"url": "加载URL", "window_id": 窗口ID}
        "webview-did-finish-load",  # {"url": "加载URL", "window_id": 窗口ID}
        "webview-new-window",  # {"url": "新窗口URL", "frame_name": "_blank"}
        "webview-page-title-updated",  # {"title": "新标题", "window_id": 窗口ID}
        "webview-page-icon-updated",  # JSON对象
        "favicon-updated",  # {"favicon": "图标URL"}
        "webview-download-started",  # {"url": "下载URL", ...} 可返回"1"阻止 (v0.3.1+)
        "postmessage-received",  # PostMessage 消息 (v1.0.2+)
        # 其他事件
        "theme-changed",  # {}
        "javascript-result",  # {"callbackId": 回调ID, "result": 执行结果}
    }

    def on(self, event: str, callback: Optional[Callable[..., Any]] = None) -> Callable[..., Any]:
        """Register an event listener

        Automatically registers events with DLL via jade_on when needed.
        Supported events: https://jade.run/guides/events/event-types

        Args:
            event: Event name to listen for
            callback: Function to call when event is emitted

        Returns:
            The callback function (for decorator usage)
        """
        # file-drop 有特殊的回调签名，单独处理
        if event == "file-drop":
            if callback is None:

                def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
                    self._register_file_drop_handler(fn)
                    return fn

                return decorator
            else:
                self._register_file_drop_handler(callback)
                return callback

        # 其他需要通过 jade_on 注册的事件
        if event in self.JADE_ON_EVENTS:
            if callback is None:

                def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
                    self._register_jade_on_event(event, fn)
                    return fn

                return decorator
            else:
                self._register_jade_on_event(event, callback)
                return callback

        # 其他事件使用父类的 on 方法
        return super().on(event, callback)

    # ==================== Typed Event Decorators ====================
    # These provide IDE type hints for event callback parameters

    def on_resized(self, callback: Callable[[int, int], Any]) -> Callable[[int, int], Any]:
        """Register a callback for window resize events.

        Args:
            callback: Function to call when window is resized.
                - width (int): New window width in pixels
                - height (int): New window height in pixels

        Example:
            @window.on_resized
            def handle_resize(width: int, height: int):
                print(f"Window resized to {width}x{height}")
        """
        self._register_jade_on_event("window-resized", callback)
        return callback

    def on_moved(self, callback: Callable[[int, int], Any]) -> Callable[[int, int], Any]:
        """Register a callback for window move events.

        Args:
            callback: Function to call when window is moved.
                - x (int): New X position in pixels
                - y (int): New Y position in pixels

        Example:
            @window.on_moved
            def handle_move(x: int, y: int):
                print(f"Window moved to ({x}, {y})")
        """
        self._register_jade_on_event("window-moved", callback)
        return callback

    def on_focused(self, callback: Callable[[], Any]) -> Callable[[], Any]:
        """Register a callback for window focus events.

        Args:
            callback: Function to call when window gains focus (no parameters).

        Example:
            @window.on_focused
            def handle_focus():
                print("Window focused")
        """
        self._register_jade_on_event("window-focused", callback)
        return callback

    def on_blurred(self, callback: Callable[[], Any]) -> Callable[[], Any]:
        """Register a callback for window blur events.

        Args:
            callback: Function to call when window loses focus (no parameters).

        Example:
            @window.on_blurred
            def handle_blur():
                print("Window lost focus")
        """
        self._register_jade_on_event("window-blurred", callback)
        return callback

    def on_closing(
        self, callback: Callable[[], Union[bool, int, None]]
    ) -> Callable[[], Union[bool, int, None]]:
        """Register a callback for window closing events.

        Return True or 1 to prevent the window from closing.

        Args:
            callback: Function to call when window is about to close.
                Returns: True/1 to prevent closing, False/0/None to allow.

        Example:
            @window.on_closing
            def handle_closing():
                if has_unsaved_changes:
                    return True  # Prevent closing
                return False  # Allow closing
        """
        self._register_jade_on_event("window-closing", callback)
        return callback

    def on_state_changed(self, callback: Callable[[bool], Any]) -> Callable[[bool], Any]:
        """Register a callback for window state change events.

        Args:
            callback: Function to call when window state changes.
                - is_maximized (bool): Whether window is maximized

        Example:
            @window.on_state_changed
            def handle_state(is_maximized: bool):
                print(f"Maximized: {is_maximized}")
        """
        self._register_jade_on_event("window-state-changed", callback)
        return callback

    def on_fullscreen_changed(self, callback: Callable[[bool], Any]) -> Callable[[bool], Any]:
        """Register a callback for window fullscreen state change events.

        Note:
            Requires JadeView DLL version 1.2 or above.

        Args:
            callback: Function to call when fullscreen state changes.
                - is_fullscreen (bool): Whether window is in fullscreen mode

        Example:
            @window.on_fullscreen_changed
            def handle_fullscreen(is_fullscreen: bool):
                print(f"Fullscreen: {is_fullscreen}")
        """
        self._register_jade_on_event("window-fullscreen", callback)
        return callback

    def on_file_dropped(
        self, callback: Callable[[List[str], int, int], Any]
    ) -> Callable[[List[str], int, int], Any]:
        """Register a callback for file drop events.

        Note: Using this event will intercept WebView's drag events,
              preventing the frontend from receiving native drag events.

        Args:
            callback: Function to call when files are dropped.
                - files (List[str]): List of dropped file paths
                - x (int): Drop X position
                - y (int): Drop Y position

        Example:
            @window.on_file_dropped
            def handle_drop(files: list, x: int, y: int):
                print(f"Dropped {len(files)} files at ({x}, {y})")
                for f in files:
                    print(f"  - {f}")
        """
        self._register_file_drop_handler(callback)
        return callback

    def on_navigate(
        self, callback: Callable[[str], Union[bool, int, None]]
    ) -> Callable[[str], Union[bool, int, None]]:
        """Register a callback for navigation events.

        Return True or 1 to prevent navigation.

        Args:
            callback: Function to call before navigation.
                - url (str): Target URL
                Returns: True/1 to prevent navigation, False/0/None to allow.

        Example:
            @window.on_navigate
            def handle_navigate(url: str):
                if "dangerous" in url:
                    return True  # Block navigation
                print(f"Navigating to: {url}")
        """
        self._register_jade_on_event("webview-will-navigate", callback)
        return callback

    def on_page_loaded(self, callback: Callable[[str], Any]) -> Callable[[str], Any]:
        """Register a callback for page load complete events.

        Args:
            callback: Function to call when page finishes loading.
                - url (str): Loaded page URL

        Example:
            @window.on_page_loaded
            def handle_loaded(url: str):
                print(f"Page loaded: {url}")
        """
        self._register_jade_on_event("webview-did-finish-load", callback)
        return callback

    def on_title_updated(self, callback: Callable[[str], Any]) -> Callable[[str], Any]:
        """Register a callback for page title update events.

        Args:
            callback: Function to call when page title changes.
                - title (str): New page title

        Example:
            @window.on_title_updated
            def handle_title(title: str):
                print(f"Title changed to: {title}")
        """
        self._register_jade_on_event("webview-page-title-updated", callback)
        return callback

    def on_new_window(
        self, callback: Callable[[str, str], Union[bool, int, None]]
    ) -> Callable[[str, str], Union[bool, int, None]]:
        """Register a callback for new window request events.

        Return True or 1 to prevent opening new window.

        Args:
            callback: Function to call when new window is requested.
                - url (str): URL for new window
                - frame_name (str): Target frame name (e.g., "_blank")
                Returns: True/1 to prevent, False/0/None to allow.

        Example:
            @window.on_new_window
            def handle_new_window(url: str, frame_name: str):
                print(f"New window requested: {url}")
                # Open in same window instead
                window.navigate(url)
                return True  # Prevent new window
        """
        self._register_jade_on_event("webview-new-window", callback)
        return callback

    def on_js_result(self, callback: Callable[[int, Any], Any]) -> Callable[[int, Any], Any]:
        """Register a callback for JavaScript execution result events.

        This listens to the native javascript-result event from the DLL.
        For simpler usage, consider using execute_js() with a callback parameter.

        Args:
            callback: Function to call when JS execution completes.
                - callback_id (int): The callback ID
                - result (Any): The execution result

        Example:
            @window.on_js_result
            def handle_js_result(callback_id: int, result):
                print(f"JS result [{callback_id}]: {result}")
        """
        self._register_jade_on_event("javascript-result", callback)
        return callback

    def on_download_started(
        self, callback: Callable[[str, str], Union[bool, int, None]]
    ) -> Callable[[str, str], Union[bool, int, None]]:
        """Register a callback for download started events.

        Return True or 1 to prevent the download.

        Note:
            Requires JadeView DLL version 0.3.1 or above.

        Args:
            callback: Function to call when a download starts.
                - url (str): Download URL
                - filename (str): Suggested filename
                Returns: True/1 to prevent download, False/0/None to allow.

        Example:
            @window.on_download_started
            def handle_download(url: str, filename: str):
                print(f"Download: {filename} from {url}")
                if filename.endswith(".exe"):
                    return True  # Block exe downloads
                return False  # Allow download
        """
        self._register_jade_on_event("webview-download-started", callback)
        return callback

    # ==================== Internal Event Registration ====================

    def _register_jade_on_event(self, event: str, callback: Callable[..., Any]) -> None:
        """通用的 jade_on 事件注册器

        Uses pre-compiled extractors for high-performance event argument parsing.

        JadeView 1.0+: 返回值使用 jade_text_create 创建安全指针
        - 返回 NULL: 允许操作
        - 返回 "1": 阻止操作
        """
        # 添加到本地监听器
        self._listeners[event].append(callback)

        # 只注册一次到 DLL
        if event in self._registered_jade_events:
            return

        # 获取预编译的参数提取器（O(1) 查找）
        extractor = _EVENT_EXTRACTORS.get(event)

        # 创建 ctypes 回调 (返回 void)
        @GenericWindowEventCallback
        def event_callback(window_id: int, json_data: bytes):
            try:
                # 解析 JSON
                data_str = json_data.decode("utf-8") if json_data else "{}"
                data_dict = _json_loads(data_str) if data_str else {}
                logger.debug(f"Event {event}: window={window_id}, data={data_str}")

                # 提取参数
                if extractor is not None:
                    args = extractor(data_dict)
                else:
                    # 未知事件：传递解析后的字典
                    args = (data_dict,)

                # 调用所有监听器
                for cb in list(self._listeners.get(event, [])):
                    try:
                        cb(*args)
                    except Exception as e:
                        logger.error(f"Error in {event} callback: {e}")
            except Exception as e:
                logger.error(f"Error in {event} event handler: {e}")

        # 保存引用防止垃圾回收
        self._callbacks.append(event_callback)

        # 通过 jade_on 注册到 DLL (v1.0+: 返回 callback_id)
        callback_id = self.dll_manager.jade_on(
            event.encode("utf-8"),
            ctypes.cast(event_callback, ctypes.c_void_p),
        )

        # 保存 callback_id 用于后续 jade_off
        if not hasattr(self, "_jade_callback_ids"):
            self._jade_callback_ids: Dict[str, int] = {}
        self._jade_callback_ids[event] = callback_id

        self._registered_jade_events.add(event)
        logger.info(f"{event} event handler registered with DLL (callback_id={callback_id})")

    def _register_file_drop_handler(self, callback: Callable[..., Any]) -> None:
        """注册文件拖放事件处理器到 DLL

        JadeView 2.x: 原生事件名为 ``drag-drop``（含 enter/over/drop/leave 阶段），
        旧版为 ``file-drop``。这里注册 ``drag-drop``，并在收到 ``type=="drop"`` 时
        以兼容的 ``file-drop`` Python 事件分发给用户回调。
        """
        # 添加到本地监听器（对外仍用 file-drop 事件名，保持向后兼容）
        self._listeners["file-drop"].append(callback)

        # 只注册一次到 DLL
        if "drag-drop" in self._registered_jade_events:
            return

        # 创建 ctypes 回调 (返回 void)
        @FileDropCallback
        def drag_drop_callback(window_id: int, json_data: bytes):
            self._on_file_drop(window_id, json_data)

        # 保存引用防止垃圾回收
        self._callbacks.append(drag_drop_callback)

        # 通过 jade_on 注册到 DLL (返回 callback_id)
        callback_id = self.dll_manager.jade_on(
            b"drag-drop",
            ctypes.cast(drag_drop_callback, ctypes.c_void_p),
        )

        # 保存 callback_id 用于后续 jade_off
        if not hasattr(self, "_jade_callback_ids"):
            self._jade_callback_ids: Dict[str, int] = {}
        self._jade_callback_ids["drag-drop"] = callback_id

        self._registered_jade_events.add("drag-drop")
        logger.info(f"drag-drop event handler registered with DLL (callback_id={callback_id})")

    # ==================== Window Lifecycle ====================

    def show(self, url: Optional[str] = None) -> "Window":
        """Show the window

        Args:
            url: Optional URL to load

        Returns:
            Self for chaining
        """
        if url:
            self._url = url

        if self.id is None:
            self._create_window()
        else:
            self.set_visible(True)

        return self

    def hide(self) -> "Window":
        """Hide the window

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.set_visible(False)
        return self

    def close(self) -> None:
        """Close the window"""
        if self.id is not None:
            result = self.dll_manager.close_window(self.id)
            if result == 1:
                logger.info(f"Window {self.id} closed")
                self._on_closed()
            else:
                logger.error(f"Failed to close window {self.id}")

    def destroy(self) -> None:
        """Force destroy the window (alias for close)"""
        self.close()

    def run(
        self,
        url: Optional[str] = None,
        web_dir: Optional[str] = None,
        entry: str = "index.html",
        enable_dev_tools: bool = False,
    ) -> None:
        """Run the window with automatic app initialization

        This is a convenience method for simple single-window applications.
        It automatically initializes JadeUIApp if needed, shows the window,
        and runs the message loop.

        Also registers default IPC handlers for window actions (close, minimize, maximize).

        Args:
            url: URL to load (takes precedence over web_dir)
            web_dir: Local web directory path. If provided, automatically starts
                    a local server. Can be:
                    - Absolute path: "C:/myapp/web"
                    - Relative path: "web" (relative to caller's directory)
                    - None: auto-detect "web" folder in caller's directory
            entry: Entry HTML file when using web_dir (default: "index.html")
            enable_dev_tools: Whether to enable developer tools (F12)

        Example:
            # Simplest - auto-detect web folder
            from jadeui import Window
            Window(title="My App").run()

            # With explicit web directory
            Window(title="My App").run(web_dir="web")

            # With remote URL
            Window(title="My App").run(url="https://example.com")
        """
        import inspect
        import os

        from .app import JadeUIApp
        from .ipc import IPCManager
        from .server import LocalServer

        # 获取调用者的目录
        caller_frame = inspect.stack()[1]
        caller_dir = os.path.dirname(os.path.abspath(caller_frame.filename))

        # 处理 web_dir 和 url
        if url:
            self._url = url
        elif web_dir is not None:
            # 使用指定的 web 目录
            if not os.path.isabs(web_dir):
                web_dir = os.path.join(caller_dir, web_dir)
            if not os.path.isdir(web_dir):
                raise ValueError(f"web 目录不存在: {web_dir}")
            server = LocalServer()
            server_url = server.start("app", web_dir)
            self._url = f"{server_url}/{entry}"
        elif self._url is None:
            # 自动检测 web 目录
            auto_web_dir = os.path.join(caller_dir, "web")
            if os.path.isdir(auto_web_dir):
                server = LocalServer()
                server_url = server.start("app", auto_web_dir)
                self._url = f"{server_url}/{entry}"
            else:
                raise ValueError(
                    f"未指定 url 或 web_dir，且未在 {caller_dir} 下找到 web 目录。\n"
                    "请指定 url 或 web_dir 参数，或在脚本同级目录创建 web 文件夹。"
                )

        # Get or create JadeUIApp instance
        app = JadeUIApp.get_instance()
        if app is None:
            app = JadeUIApp()

        # Initialize if not already initialized
        if not app._initialized:
            app.initialize(enable_dev_tools=enable_dev_tools)

        # 注册默认的窗口操作 IPC 处理器
        ipc = IPCManager()

        @ipc.on("windowAction")
        def _handle_window_action(window_id: int, action: str) -> str:
            logger.debug(f"windowAction received: window_id={window_id}, action={action}")
            win = Window.get_window_by_id(window_id)
            if win:
                if action == "close":
                    win.close()
                elif action == "minimize":
                    win.minimize()
                elif action == "maximize":
                    win.maximize()
            else:
                logger.warning(f"Window not found: {window_id}")
            return '{"success": true}'

        # 保存 window 引用，在 on_ready 中显示
        window = self

        # 注册 on_ready 回调来显示窗口
        @app.on_ready
        def _show_window():
            window.show()

        # Run message loop
        app.run()

    def focus(self) -> "Window":
        """Focus the window

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_focus(self.id)
        return self

    # ==================== Window State ====================

    def minimize(self) -> "Window":
        """Minimize the window

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.minimize_window(self.id)
        return self

    def maximize(self) -> "Window":
        """Toggle maximize/restore for the window

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.toggle_maximize_window(self.id)
        return self

    def restore(self) -> "Window":
        """Restore the window from minimized/maximized state

        Returns:
            Self for chaining
        """
        # If maximized, toggle to restore
        if self.is_maximized:
            self.dll_manager.toggle_maximize_window(self.id)
        return self

    def set_fullscreen(self, fullscreen: bool) -> "Window":
        """Set fullscreen mode

        Note:
            Requires JadeView DLL version 0.2.1 or above.

        Args:
            fullscreen: Whether to enable fullscreen

        Returns:
            Self for chaining
        """
        self._options["fullscreen"] = fullscreen
        if self.id is not None:
            self.dll_manager.set_window_fullscreen(self.id, 1 if fullscreen else 0)
        return self

    def toggle_fullscreen(self) -> "Window":
        """Toggle fullscreen mode

        Returns:
            Self for chaining
        """
        return self.set_fullscreen(not self.is_fullscreen)

    # ==================== Window Properties ====================

    @property
    def title(self) -> str:
        """Get window title"""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        """Set window title"""
        self.set_title(value)

    def set_title(self, title: str) -> "Window":
        """Set the window title

        Args:
            title: New window title

        Returns:
            Self for chaining
        """
        self._title = title
        if self.id is not None:
            self.dll_manager.set_window_title(self.id, title.encode("utf-8"))
        return self

    @property
    def size(self) -> Tuple[int, int]:
        """Get window size as (width, height)"""
        return (self._width, self._height)

    def set_size(self, width: int, height: int) -> "Window":
        """Set the window size

        Args:
            width: New width in pixels
            height: New height in pixels

        Returns:
            Self for chaining
        """
        self._width = width
        self._height = height
        if self.id is not None:
            self.dll_manager.set_window_size(self.id, width, height)
        return self

    def set_min_size(self, width: int, height: int) -> "Window":
        """Set minimum window size

        Args:
            width: Minimum width
            height: Minimum height

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_min_size(self.id, width, height)
        return self

    def set_max_size(self, width: int, height: int) -> "Window":
        """Set maximum window size

        Args:
            width: Maximum width (0 for no limit)
            height: Maximum height (0 for no limit)

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_max_size(self.id, width, height)
        return self

    @property
    def position(self) -> Tuple[int, int]:
        """Get window position as (x, y)"""
        return (self._options.get("x", -1), self._options.get("y", -1))

    def set_position(self, x: int, y: int) -> "Window":
        """Set the window position

        Args:
            x: X position
            y: Y position

        Returns:
            Self for chaining
        """
        self._options["x"] = x
        self._options["y"] = y
        if self.id is not None:
            self.dll_manager.set_window_position(self.id, x, y)
        return self

    def center(self) -> "Window":
        """Center the window on screen

        Returns:
            Self for chaining
        """
        return self.set_position(-1, -1)

    def set_visible(self, visible: bool) -> "Window":
        """Set window visibility

        Args:
            visible: Whether window should be visible

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_visible(self.id, 1 if visible else 0)
        return self

    def set_always_on_top(self, on_top: bool) -> "Window":
        """Set always on top

        Args:
            on_top: Whether window should stay on top

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_always_on_top(self.id, 1 if on_top else 0)
        return self

    def set_resizable(self, resizable: bool) -> "Window":
        """Set whether window is resizable

        Args:
            resizable: Whether window can be resized

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_resizable(self.id, 1 if resizable else 0)
        return self

    # ==================== Theme & Appearance ====================

    def set_theme(self, theme: str) -> "Window":
        """Set window theme

        Args:
            theme: Theme name ('Light', 'Dark', 'System')

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_theme(self.id, theme.encode("utf-8"))
        return self

    def get_theme(self) -> str:
        """Get current window theme

        JadeView 2.x: ``get_window_theme(window_id)`` 直接返回整数
        (1=Dark, 0=Light)，表示当前实际生效的外观。

        Returns:
            ``Theme.DARK`` 或 ``Theme.LIGHT``；窗口未创建时回退 ``Theme.SYSTEM``。
        """
        if self.id is not None:
            result = self.dll_manager.get_window_theme(self.id)
            return Theme.DARK if result == 1 else Theme.LIGHT
        return Theme.SYSTEM

    def set_backdrop(self, backdrop: str) -> "Window":
        """Set window backdrop material (Windows 11)

        Args:
            backdrop: Backdrop type ('mica', 'micaalt', 'acrylic')

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.set_window_backdrop(self.id, backdrop.encode("utf-8"))
        else:
            # 保存设置，在窗口创建后应用
            self._pending_backdrop = backdrop
        return self

    # ==================== Window Extras (JadeView 2.x) ====================

    def set_zoom(self, level: float) -> "Window":
        """设置 WebView 缩放级别 (1.0 = 100%)"""
        if self.id is not None:
            self.dll_manager.set_webview_zoom(self.id, ctypes.c_double(level))
        return self

    def set_content_protection(self, enabled: bool = True) -> "Window":
        """动态开关内容保护（禁止截图/录屏）"""
        if self.id is not None:
            self.dll_manager.set_content_protection(self.id, 1 if enabled else 0)
        return self

    def set_enabled(self, enabled: bool = True) -> "Window":
        """启用/禁用窗口（禁用时不响应输入）"""
        if self.id is not None:
            self.dll_manager.set_window_enabled(self.id, 1 if enabled else 0)
        return self

    def request_redraw(self) -> "Window":
        """请求窗口重绘"""
        if self.id is not None:
            self.dll_manager.request_redraw(self.id)
        return self

    def set_background_color(self, color: Any) -> "Window":
        """设置窗口纯色背景（接受 RGBA / dict / "#RRGGBBAA" 字符串）"""
        if self.id is not None:
            hex_color = rgba_to_hex(color)
            if hex_color is not None:
                self.dll_manager.set_window_background_color(self.id, hex_color)
        return self

    def set_frame_style(self, style: str) -> "Window":
        """设置窗口边框样式：normal / no-titlebar / borderless"""
        if self.id is not None:
            self.dll_manager.set_window_frame_style(self.id, style.encode("utf-8"))
        return self

    def get_bounds(self) -> Optional[dict]:
        """获取窗口位置与尺寸 (JSON: 含 x/y/width/height 等)"""
        if self.id is None or not self.dll_manager.has_function("get_window_bounds"):
            return None
        buf = ctypes.create_string_buffer(512)
        if self.dll_manager.get_window_bounds(self.id, buf, 512) > 0:
            try:
                return _json_loads(buf.value.decode("utf-8", "replace"))
            except ValueError:
                return None
        return None

    def get_hwnd(self) -> int:
        """获取原生窗口句柄 HWND

        注意：仅 ``create_borderless_webview_window`` 创建的无边框窗口返回有效句柄，
        标准窗口返回 0。
        """
        if self.id is not None and self.dll_manager.has_function("get_window_hwnd"):
            return int(self.dll_manager.get_window_hwnd(self.id))
        return 0

    def set_ignore_cursor_events(self, ignore: bool = True) -> "Window":
        """设置鼠标穿透（忽略光标事件）"""
        if self.id is not None:
            self.dll_manager.set_window_ignore_cursor_events(self.id, 1 if ignore else 0)
        return self

    def set_progress(self, progress: int, state: Optional[int] = None) -> "Window":
        """设置任务栏进度

        Args:
            progress: 进度值 (0-100)
            state: 进度状态（Windows ITaskbarList3 语义）：
                0=无进度, 1=不确定, 2=正常, 4=错误(红), 8=暂停(黄)。
                省略时：progress>0 自动用「正常」(2)，progress<=0 用「无进度」(0)。
        """
        if self.id is not None:
            if state is None:
                state = 2 if progress > 0 else 0
            self.dll_manager.set_window_progress(self.id, progress, state)
        return self

    def flash(self, count: int = 1) -> "Window":
        """任务栏图标闪烁以提示用户

        Args:
            count: 闪烁次数
        """
        if self.id is not None:
            self.dll_manager.flash_window(self.id, count)
        return self

    def open_devtools(self) -> "Window":
        """打开开发者工具"""
        if self.id is not None:
            self.dll_manager.open_devtools(self.id)
        return self

    def close_devtools(self) -> "Window":
        """关闭开发者工具"""
        if self.id is not None:
            self.dll_manager.close_devtools(self.id)
        return self

    @property
    def is_devtools_open(self) -> bool:
        """开发者工具是否已打开"""
        if self.id is not None and self.dll_manager.has_function("is_devtools_open"):
            return self.dll_manager.is_devtools_open(self.id) == 1
        return False

    def get_current_url(self) -> Optional[str]:
        """获取当前 WebView 实际 URL"""
        if self.id is None or not self.dll_manager.has_function("get_webview_url"):
            return None
        buf = ctypes.create_string_buffer(4096)
        if self.dll_manager.get_webview_url(self.id, buf, 4096) > 0:
            return buf.value.decode("utf-8", "replace")
        return None

    def clear_browsing_data(self) -> "Window":
        """清除该窗口 WebView 的浏览数据（缓存/cookie 等）"""
        if self.id is not None:
            self.dll_manager.clear_browsing_data(self.id)
        return self

    def print_page(self) -> "Window":
        """打开打印对话框打印当前页面（WebView2 内置）"""
        if self.id is not None and self.dll_manager.has_function("jade_print"):
            self.dll_manager.jade_print(self.id)
        return self

    def set_titlebar_overlay(
        self, height: int = 0, icon_color: str = "", hover_bg: str = ""
    ) -> "Window":
        """设置标题栏覆盖层样式（Windows）

        Args:
            height: 覆盖层高度（<=0 不修改）
            icon_color: 图标颜色十六进制（如 "#FFFFFF"）
            hover_bg: 悬浮背景色十六进制
        """
        if self.id is not None and self.dll_manager.has_function("set_titlebar_overlay_style"):
            self.dll_manager.set_titlebar_overlay_style(
                self.id,
                height,
                icon_color.encode("utf-8") if icon_color else None,
                hover_bg.encode("utf-8") if hover_bg else None,
            )
        return self

    # ==================== WebView Operations ====================

    def load_url(self, url: str) -> "Window":
        """Navigate to a URL

        Args:
            url: URL to load

        Returns:
            Self for chaining
        """
        self._url = url
        if self.id is not None:
            # JadeView 2.x: navigate_to_url(window_id, url, headers_json)
            self.dll_manager.navigate_to_url(self.id, url.encode("utf-8"), None)
        return self

    def navigate(self, url: str) -> "Window":
        """Navigate to a URL (alias for load_url)

        Args:
            url: URL to load

        Returns:
            Self for chaining
        """
        return self.load_url(url)

    def execute_js(
        self,
        script: str,
        callback: Optional[Callable[[Any], Any]] = None,
    ) -> "Window":
        """Execute JavaScript in the window

        Args:
            script: JavaScript code to execute
            callback: Optional callback function to receive the result.
                      Will be called with the JavaScript execution result.
                      Note: Requires registering javascript-result event handler.

        Returns:
            Self for chaining

        Example:
            # Without callback
            window.execute_js("console.log('Hello')")

            # With callback
            def on_result(result):
                print(f"Result: {result}")
            window.execute_js("1 + 1", callback=on_result)
        """
        if self.id is not None:
            if callback is not None:
                # 生成唯一的 callbackId 并注册回调
                self._js_callback_id_counter += 1
                callback_id = self._js_callback_id_counter
                self._js_callbacks[callback_id] = callback

                # 确保已注册 javascript-result 事件处理器
                self._ensure_js_result_handler()

                # 包装脚本以返回 callbackId
                # JadeView 2.x: 前端 IPC 统一用 jade.invoke（jade.ipcSend 已移除）
                wrapped_script = f"""
(function() {{
    try {{
        var result = eval({repr(script)});
        if (typeof jade !== 'undefined' && jade.invoke) {{
            jade.invoke('__js_result__', JSON.stringify({{
                callbackId: {callback_id},
                result: result
            }}));
        }}
    }} catch (e) {{
        if (typeof jade !== 'undefined' && jade.invoke) {{
            jade.invoke('__js_result__', JSON.stringify({{
                callbackId: {callback_id},
                error: e.message
            }}));
        }}
    }}
}})();
"""
                self.dll_manager.execute_javascript(self.id, wrapped_script.encode("utf-8"))
            else:
                self.dll_manager.execute_javascript(self.id, script.encode("utf-8"))
        return self

    def _ensure_js_result_handler(self) -> None:
        """确保已注册 JavaScript 结果处理器"""
        if "__js_result__" in self._registered_jade_events:
            return

        from .ipc import IPCManager

        ipc = IPCManager(self.dll_manager)

        @ipc.on("__js_result__")
        def handle_js_result(window_id: int, message: str) -> int:
            try:
                data = _json_loads(message) if message else {}
                callback_id = data.get("callbackId")
                result = data.get("result")
                error = data.get("error")

                if callback_id and callback_id in self._js_callbacks:
                    callback = self._js_callbacks.pop(callback_id)
                    if error:
                        logger.error(f"JS execution error: {error}")
                        callback(None)
                    else:
                        callback(result)
            except Exception as e:
                logger.error(f"Error handling JS result: {e}")
            return 1

        self._registered_jade_events.add("__js_result__")
        logger.info("JavaScript result handler registered")

    def eval(self, script: str, callback: Optional[Callable[[Any], Any]] = None) -> "Window":
        """Execute JavaScript (alias for execute_js)

        Args:
            script: JavaScript code to execute
            callback: Optional callback function to receive the result

        Returns:
            Self for chaining
        """
        return self.execute_js(script, callback)

    def reload(self) -> "Window":
        """Reload the current page in the WebView

        Reloads the current page content, equivalent to browser's refresh button.

        Note:
            Requires JadeView DLL version 0.2 or above.

        Returns:
            Self for chaining
        """
        if self.id is not None:
            self.dll_manager.reload_webview_window(self.id)
        return self

    def refresh(self) -> "Window":
        """Refresh the current page (alias for reload)

        Returns:
            Self for chaining
        """
        return self.reload()

    # ==================== State Queries ====================

    @property
    def is_visible(self) -> bool:
        """Check if window is visible"""
        if self.id is not None:
            return self.dll_manager.is_window_visible(self.id) == 1
        return False

    @property
    def is_maximized(self) -> bool:
        """Check if window is maximized"""
        if self.id is not None:
            return self.dll_manager.is_window_maximized(self.id) == 1
        return False

    @property
    def is_minimized(self) -> bool:
        """Check if window is minimized"""
        if self.id is not None:
            return self.dll_manager.is_window_minimized(self.id) == 1
        return False

    @property
    def is_focused(self) -> bool:
        """Check if window is focused"""
        if self.id is not None:
            return self.dll_manager.is_window_focused(self.id) == 1
        return False

    @property
    def is_fullscreen(self) -> bool:
        """Check if window is in fullscreen mode

        Note:
            Requires JadeView DLL version 0.2.1 or above for accurate query.
            Falls back to local state tracking for older versions.
        """
        if self.id is not None:
            # Try to query DLL first (JadeView 0.2.1+)
            if self.dll_manager.has_function("is_window_fullscreen"):
                return self.dll_manager.is_window_fullscreen(self.id) == 1
        # Fallback to local tracking
        return self._options.get("fullscreen", False)

    # ==================== Window Creation ====================

    def _create_window(self) -> None:
        """Create the actual window using the DLL"""
        # Prepare background color (JadeView 2.x: 改为 "#RRGGBBAA" 字符串)
        background_color = rgba_to_hex(self._options.get("background_color"))

        # Prepare theme
        theme = self._options.get("theme", Theme.SYSTEM)
        if isinstance(theme, str):
            theme = theme.encode("utf-8")

        # Resolve frame_style (JadeView 2.x: 合并 remove_titlebar / borderless)
        # 优先使用显式 frame_style；否则从旧选项推导。
        frame_style = self._options.get("frame_style")
        if frame_style is None:
            if self._options.get("borderless"):
                frame_style = "borderless"
            elif self._options.get("remove_titlebar"):
                frame_style = "no-titlebar"
            else:
                frame_style = "normal"
        if isinstance(frame_style, str):
            frame_style = frame_style.encode("utf-8")

        # Create window options (JadeView 2.x)
        window_options = WebViewWindowOptions(
            title=self._title.encode("utf-8"),
            width=self._width,
            height=self._height,
            resizable=self._options.get("resizable", True),
            frame_style=frame_style,
            transparent=self._options.get("transparent", False),
            background_color=background_color,
            always_on_top=self._options.get("always_on_top", False),
            theme=theme,
            maximized=self._options.get("maximized", False),
            maximizable=self._options.get("maximizable", True),
            minimizable=self._options.get("minimizable", True),
            x=self._options.get("x", -1),
            y=self._options.get("y", -1),
            min_width=self._options.get("min_width", 0),
            min_height=self._options.get("min_height", 0),
            max_width=self._options.get("max_width", 0),
            max_height=self._options.get("max_height", 0),
            fullscreen=self._options.get("fullscreen", False),
            focus=self._options.get("focus", True),
            hide_window=self._options.get("hide_window", False),
            use_page_icon=self._options.get("use_page_icon", True),
            content_protection=self._options.get("content_protection", False),
            auto_save_state=self._options.get("auto_save_state", False),  # JadeView 2.x
        )

        # Prepare WebView settings
        user_agent = self._options.get("user_agent")
        preload_js = self._options.get("preload_js")
        postmessage_whitelist = self._options.get("postmessage_whitelist")
        cors_whitelist = self._options.get("cors_whitelist")
        proxy_url = self._options.get("proxy_url")

        # JadeView 2.x: 语义由 disable_right_click 反转为 allow_right_click
        allow_right_click = self._options.get(
            "allow_right_click", not self._options.get("disable_right_click", False)
        )

        settings = WebViewSettings(
            autoplay=self._options.get("autoplay", False),
            background_throttling=self._options.get("background_throttling", False),
            allow_right_click=allow_right_click,
            ua=user_agent.encode("utf-8") if user_agent else None,
            preload_js=preload_js.encode("utf-8") if preload_js else None,
            allow_fullscreen=self._options.get("allow_fullscreen", True),
            postmessage_whitelist=postmessage_whitelist.encode("utf-8")
            if postmessage_whitelist
            else None,
            cors_whitelist=cors_whitelist.encode("utf-8") if cors_whitelist else None,
            autofill=self._options.get("autofill", False),
            general_autofill_enabled=self._options.get("general_autofill_enabled", False),
            incognito=self._options.get("incognito", False),
            disable_clipboard=self._options.get("disable_clipboard", False),
            proxy_url=proxy_url.encode("utf-8") if proxy_url else None,
            focused=self._options.get("focused", self._options.get("focus", True)),
        )

        # Prepare URL
        url_bytes = self._url.encode("utf-8") if self._url else b""

        # Create window
        try:
            self.id = self.dll_manager.create_webview_window(
                url_bytes,
                0,  # parent window ID
                ctypes.byref(window_options),
                ctypes.byref(settings),
            )

            if self.id == 0:
                raise WindowCreationError("Failed to create window")

            logger.info(f"Window created with ID: {self.id}")

            # Register in window registry
            Window._windows[self.id] = self

            # Apply theme and backdrop after creation
            if theme:
                self.dll_manager.set_window_theme(self.id, theme)

            # 应用 backdrop（优先使用 set_backdrop 设置的值）
            backdrop = self._pending_backdrop or self._options.get("backdrop")
            if backdrop:
                self.dll_manager.set_window_backdrop(self.id, backdrop.encode("utf-8"))
                self._pending_backdrop = None  # 清除待处理设置

            # Set up event handlers
            self._setup_event_handlers()

            # Emit created event
            self.emit("created", self)

        except Exception as e:
            raise WindowCreationError(f"Failed to create window: {e}")

    def _setup_event_handlers(self) -> None:
        """Set up event handlers for the window

        Uses jade_on to register global event handlers (only once per class).
        This replaces the deprecated set_window_event_handlers API.
        """
        if self.id is None:
            return

        # Register global handlers only once (class-level)
        if not Window._global_handlers_registered:
            self._register_global_event_handlers()
            Window._global_handlers_registered = True

    @classmethod
    def _register_global_event_handlers(cls) -> None:
        """Register global event handlers using jade_on

        This replaces the deprecated set_window_event_handlers API.
        All window events are now handled through jade_on.
        """
        dll = DLLManager()

        # Register window-closed event handler
        @GenericWindowEventCallback
        def window_closed_callback(window_id: int, json_data: bytes) -> int:
            try:
                window = cls._windows.get(window_id)
                if window:
                    window._on_closed()
            except Exception as e:
                logger.error(f"Error in window-closed handler: {e}")
            return 0

        cls._global_callbacks.append(window_closed_callback)
        cls._global_callback_ids = getattr(cls, "_global_callback_ids", {})
        cls._global_callback_ids["window-closed"] = dll.jade_on(
            b"window-closed",
            ctypes.cast(window_closed_callback, ctypes.c_void_p),
        )

        # Register page load events via jade_on
        # webview-did-finish-load: {"url": "...", "window_id": ...}
        @GenericWindowEventCallback
        def page_load_callback(window_id: int, json_data: bytes) -> int:
            try:
                data_str = json_data.decode("utf-8") if json_data else "{}"
                window = cls._windows.get(window_id)
                if window:
                    data = _json_loads(data_str) if data_str else {}
                    url = data.get("url", "")
                    logger.debug(f"Page load: {window_id}, {url}")
                    window.emit("page-loaded", url, "complete")
            except Exception as e:
                logger.error(f"Error in page-load handler: {e}")
            return 0

        cls._global_callbacks.append(page_load_callback)
        cls._global_callback_ids["webview-did-finish-load"] = dll.jade_on(
            b"webview-did-finish-load",
            ctypes.cast(page_load_callback, ctypes.c_void_p),
        )

        logger.info("Global event handlers registered via jade_on")

    def _on_closed(self) -> None:
        """Handle window closed"""
        if self.id is not None:
            if self.id in Window._windows:
                del Window._windows[self.id]
            self.emit("closed")
            self.id = None

    def _on_file_drop(self, window_id: int, json_data: bytes) -> None:
        """Handle drag-drop events

        JadeView 2.x 数据格式:
            {"type": "enter"|"over"|"drop"|"leave", "paths": [...], "x": x, "y": y}
        其中 ``paths`` 仅在 enter/drop 阶段存在。仅在 ``drop`` 阶段对外分发
        ``file-drop`` 事件（携带文件路径列表与坐标）。同时分发底层 ``drag-drop``
        事件以便需要 enter/over/leave 阶段的高级用法。

        兼容旧格式 ``{"files": [...], "x", "y"}``（无 type 字段时按 drop 处理）。
        """
        try:
            data_str = json_data.decode("utf-8") if json_data else "{}"
            data = _json_loads(data_str) if data_str else {}

            phase = data.get("type")
            x = data.get("x", 0)
            y = data.get("y", 0)
            paths = data.get("paths", data.get("files", []))

            # 透传底层 drag-drop 事件（enter/over/drop/leave）
            self.emit("drag-drop", data)

            # 仅在 drop 阶段（或旧格式无 type）时触发兼容的 file-drop 回调
            if phase is None or phase == "drop":
                logger.debug(f"File drop: window={window_id}, paths={paths}, x={x}, y={y}")
                self.emit("file-drop", paths, x, y)
        except Exception as e:
            logger.error(f"Error parsing drag-drop data: {e}")

    # ==================== Static Methods ====================

    @staticmethod
    def get_window_count() -> int:
        """Get the number of active windows

        Returns:
            Number of active windows
        """
        dll = DLLManager()
        if dll.is_loaded():
            return dll.get_window_count()
        return 0

    @staticmethod
    def get_window_by_id(window_id: int) -> Optional["Window"]:
        """Get a window by its ID

        Args:
            window_id: Window ID

        Returns:
            Window instance or None
        """
        return Window._windows.get(window_id)

    @staticmethod
    def get_all_windows() -> list["Window"]:
        """Get all active windows

        Returns:
            List of active Window instances
        """
        return list(Window._windows.values())

    # ==================== Dunder Methods ====================

    def __repr__(self) -> str:
        return f"Window(id={self.id}, title='{self._title}', size={self._width}x{self._height})"

    def __enter__(self) -> "Window":
        """Context manager entry"""
        if self.id is None:
            self._create_window()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit"""
        self.close()
