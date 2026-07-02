"""
JadeUI Type Definitions

ctypes structures and callback type definitions for JadeView DLL interface.

JadeView 1.0+ 重要变更:
回调函数返回 const char* 类型，需使用 jade_text_create 创建安全指针。
- 返回 NULL (None): 允许操作
- 返回 "1": 阻止操作
- 返回其他文本: IPC 响应数据
"""

import ctypes

# ==================== Callback Function Types ====================
# JadeView: 回调类型定义
# 使用 WINFUNCTYPE (stdcall) - JadeView DLL 使用 stdcall 调用约定
import sys
from typing import Callable, Optional

if sys.platform == "win32":
    _FUNCTYPE = ctypes.WINFUNCTYPE
else:
    _FUNCTYPE = ctypes.CFUNCTYPE

# 事件回调: window_id, event_data -> void*
# 用于通过 jade_on 注册的所有事件 (app-ready, load, file-drop 等)
GenericWindowEventCallback = _FUNCTYPE(
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.c_char_p,
)

# IPC 回调 (jade.invoke): window_id, message -> void*
# 返回 jade_text_create 创建的指针，或 0/NULL 表示无返回
IpcCallback = _FUNCTYPE(
    ctypes.c_void_p,  # 返回 void*
    ctypes.c_uint,
    ctypes.c_char_p,
)

# 应用就绪回调: 与通用事件回调相同
AppReadyCallback = GenericWindowEventCallback

# 所有窗口关闭回调: 与通用事件回调相同
WindowAllClosedCallback = GenericWindowEventCallback

# file-drop 事件回调: 与通用事件回调相同
FileDropCallback = GenericWindowEventCallback

# ==================== Legacy Callback Types ====================

WindowEventCallback = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p
)
PageLoadCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_char_p)


# Data structures
class RGBA(ctypes.Structure):
    """RGBA color structure

    JadeView 2.x 起，原生 ``WebViewWindowOptions.background_color`` 改为
    ``#RRGGBBAA`` 十六进制字符串。RGBA 仍保留作为 Python 侧便捷类型，
    通过 :func:`rgba_to_hex` 转换为底层所需的字符串。
    """

    _fields_ = [
        ("r", ctypes.c_int),
        ("g", ctypes.c_int),
        ("b", ctypes.c_int),
        ("a", ctypes.c_int),
    ]

    def __init__(self, r: int = 255, g: int = 255, b: int = 255, a: int = 255):
        super().__init__(r, g, b, a)

    def to_hex(self) -> str:
        """转换为 ``#RRGGBBAA`` 十六进制字符串"""
        return f"#{self.r & 0xFF:02x}{self.g & 0xFF:02x}{self.b & 0xFF:02x}{self.a & 0xFF:02x}"

    def __repr__(self) -> str:
        return f"RGBA(r={self.r}, g={self.g}, b={self.b}, a={self.a})"


def rgba_to_hex(color: object) -> Optional[bytes]:
    """将多种背景色表示转换为底层所需的 ``#RRGGBBAA`` 字节串。

    支持:
        - ``RGBA`` 实例
        - ``dict``，如 ``{"r":255,"g":255,"b":255,"a":255}``
        - ``str``/``bytes`` 十六进制字符串（``"#RRGGBBAA"`` / ``"#RRGGBB"``）
        - ``None`` -> ``None``（底层使用默认值）
    """
    if color is None:
        return None
    if isinstance(color, RGBA):
        return color.to_hex().encode("utf-8")
    if isinstance(color, dict):
        return RGBA(
            color.get("r", 255),
            color.get("g", 255),
            color.get("b", 255),
            color.get("a", 255),
        ).to_hex().encode("utf-8")
    if isinstance(color, bytes):
        return color
    if isinstance(color, str):
        return color.encode("utf-8")
    raise TypeError(f"Unsupported background_color type: {type(color)!r}")


class WebViewWindowOptions(ctypes.Structure):
    """WebView window configuration options

    字段顺序与 JadeView 2.3.0-beta.9 原生头文件 ``WebViewWindowOptions`` 完全一致。

    与 1.x 的破坏性变更:
        - ``remove_titlebar`` + ``borderless`` 合并为单一 ``frame_style``
          ("normal" / "no-titlebar" / "borderless")
        - ``background_color`` 由 RGBA 结构体改为 ``#RRGGBBAA`` 字符串指针
        - 移除 ``no_center``
        - 新增 ``auto_save_state``
        - 2.3.0-beta.6 末尾追加 ``skip_taskbar`` / ``no_activate``
    """

    _fields_ = [
        ("title", ctypes.c_char_p),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("resizable", ctypes.c_int),
        ("frame_style", ctypes.c_char_p),  # normal / no-titlebar / borderless
        ("transparent", ctypes.c_int),
        ("background_color", ctypes.c_char_p),  # "#RRGGBBAA"
        ("always_on_top", ctypes.c_int),
        ("theme", ctypes.c_char_p),
        ("maximized", ctypes.c_int),
        ("maximizable", ctypes.c_int),
        ("minimizable", ctypes.c_int),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("min_width", ctypes.c_int),
        ("min_height", ctypes.c_int),
        ("max_width", ctypes.c_int),
        ("max_height", ctypes.c_int),
        ("fullscreen", ctypes.c_int),
        ("focus", ctypes.c_int),
        ("hide_window", ctypes.c_int),
        ("use_page_icon", ctypes.c_int),
        ("content_protection", ctypes.c_int),  # 内容保护（禁止截图）
        ("auto_save_state", ctypes.c_int),  # JadeView 2.x: 自动保存窗口状态
        ("skip_taskbar", ctypes.c_int),  # JadeView 2.3: 不进任务栏/Alt-Tab
        ("no_activate", ctypes.c_int),  # JadeView 2.3: 显示/点击时不抢焦点
    ]

    def __init__(
        self,
        title: bytes = b"Window",
        width: int = 800,
        height: int = 600,
        resizable: bool = True,
        frame_style: bytes = b"normal",
        transparent: bool = False,
        background_color: Optional[bytes] = None,
        always_on_top: bool = False,
        theme: bytes = b"System",
        maximized: bool = False,
        maximizable: bool = True,
        minimizable: bool = True,
        x: int = -1,
        y: int = -1,
        min_width: int = 0,
        min_height: int = 0,
        max_width: int = 0,
        max_height: int = 0,
        fullscreen: bool = False,
        focus: bool = True,
        hide_window: bool = False,
        use_page_icon: bool = True,
        content_protection: bool = False,
        auto_save_state: bool = False,
        skip_taskbar: bool = False,
        no_activate: bool = False,
    ):
        super().__init__(
            title,
            width,
            height,
            int(resizable),
            frame_style,
            int(transparent),
            background_color,
            int(always_on_top),
            theme,
            int(maximized),
            int(maximizable),
            int(minimizable),
            x,
            y,
            min_width,
            min_height,
            max_width,
            max_height,
            int(fullscreen),
            int(focus),
            int(hide_window),
            int(use_page_icon),
            int(content_protection),
            int(auto_save_state),
            int(skip_taskbar),
            int(no_activate),
        )


class WebViewSettings(ctypes.Structure):
    """WebView behavior settings

    字段顺序与 JadeView 2.2.4 原生头文件 ``WebViewSettings`` 完全一致。

    与 1.x 的破坏性变更:
        - ``disable_right_click`` 改为 ``allow_right_click``（语义反转：1=允许）
        - 新增 ``cors_whitelist`` / ``autofill`` / ``general_autofill_enabled`` /
          ``incognito`` / ``disable_clipboard`` / ``proxy_url`` / ``focused``
    """

    _fields_ = [
        ("autoplay", ctypes.c_int),
        ("background_throttling", ctypes.c_int),
        ("allow_right_click", ctypes.c_int),  # 1=允许右键菜单, 0=禁用
        ("ua", ctypes.c_char_p),
        ("preload_js", ctypes.c_char_p),
        ("allow_fullscreen", ctypes.c_int),
        ("postmessage_whitelist", ctypes.c_char_p),  # 单个域名
        ("cors_whitelist", ctypes.c_char_p),  # 逗号分隔多个域名
        ("autofill", ctypes.c_int),  # 账号/密码自动填充
        ("general_autofill_enabled", ctypes.c_int),  # 通用表单自动填充
        ("incognito", ctypes.c_int),  # 无痕模式
        ("disable_clipboard", ctypes.c_int),  # 禁用剪贴板读写
        ("proxy_url", ctypes.c_char_p),  # 代理 URL，如 "http://host:port"
        ("focused", ctypes.c_int),  # 初始是否自动获取焦点
    ]

    def __init__(
        self,
        autoplay: bool = False,
        background_throttling: bool = False,
        allow_right_click: bool = True,
        ua: Optional[bytes] = None,
        preload_js: Optional[bytes] = None,
        allow_fullscreen: bool = True,
        postmessage_whitelist: Optional[bytes] = None,
        cors_whitelist: Optional[bytes] = None,
        autofill: bool = False,
        general_autofill_enabled: bool = False,
        incognito: bool = False,
        disable_clipboard: bool = False,
        proxy_url: Optional[bytes] = None,
        focused: bool = True,
    ):
        super().__init__(
            int(autoplay),
            int(background_throttling),
            int(allow_right_click),
            ua,
            preload_js,
            int(allow_fullscreen),
            postmessage_whitelist,
            cors_whitelist,
            int(autofill),
            int(general_autofill_enabled),
            int(incognito),
            int(disable_clipboard),
            proxy_url,
            int(focused),
        )


# ==================== Dialog Params (v1.3.0+) ====================
# 根据官方文档: https://jade.run/guides/dialog-api#结构体定义

# 对话框回调函数类型: void (*callback)(const char*)
DialogCallback = _FUNCTYPE(None, ctypes.c_char_p)


class FileDialogParams(ctypes.Structure):
    """文件对话框参数结构体（打开/保存共用）

    用于 jade_dialog_show_open_dialog / jade_dialog_show_save_dialog
    及其 ``*_async`` 变体。

    JadeView 2.x 破坏性变更:
        - 打开/保存合并为单一结构体
        - 移除 ``blocking`` / ``callback`` 字段（同步函数直接返回结果，
          异步走独立的 ``*_async`` 函数并显式传入回调）
        - ``properties`` 改为 JSON 格式
    """

    _fields_ = [
        ("window_id", ctypes.c_uint32),  # 关联窗口 ID
        ("title", ctypes.c_char_p),  # 对话框标题
        ("default_path", ctypes.c_char_p),  # 默认路径
        ("button_label", ctypes.c_char_p),  # 确认按钮文本
        ("filters", ctypes.c_char_p),  # 文件过滤器（JSON格式）
        ("properties", ctypes.c_char_p),  # 对话框属性（JSON格式）
    ]

    def __init__(
        self,
        window_id: int = 0,
        title: Optional[bytes] = None,
        default_path: Optional[bytes] = None,
        button_label: Optional[bytes] = None,
        filters: Optional[bytes] = None,
        properties: Optional[bytes] = None,
    ):
        super().__init__(
            window_id,
            title,
            default_path,
            button_label,
            filters,
            properties,
        )


# 向后兼容别名（1.x 中分别为 Open/Save 两个结构体）
OpenDialogParams = FileDialogParams
SaveDialogParams = FileDialogParams


class MessageBoxParams(ctypes.Structure):
    """消息框参数结构体

    用于 jade_dialog_show_message_box 及其 ``_async`` 变体。

    JadeView 2.x 破坏性变更:
        - 移除 ``blocking`` / ``callback`` 字段
        - ``buttons`` 改为 JSON 格式（1.x 为 ``|`` 分隔）
    """

    _fields_ = [
        ("window_id", ctypes.c_uint32),  # 窗口 ID
        ("title", ctypes.c_char_p),  # 消息框标题
        ("message", ctypes.c_char_p),  # 消息正文
        ("detail", ctypes.c_char_p),  # 详细信息
        ("buttons", ctypes.c_char_p),  # 按钮列表（JSON格式，如 ["确定","取消"]）
        ("default_id", ctypes.c_int),  # 默认选中的按钮索引
        ("cancel_id", ctypes.c_int),  # 取消按钮的索引
        ("type_", ctypes.c_char_p),  # 类型: none / info / warning / error
    ]

    def __init__(
        self,
        window_id: int = 0,
        title: Optional[bytes] = None,
        message: Optional[bytes] = None,
        detail: Optional[bytes] = None,
        buttons: Optional[bytes] = None,
        default_id: int = 0,
        cancel_id: int = -1,
        type_: Optional[bytes] = None,
    ):
        super().__init__(
            window_id,
            title,
            message,
            detail,
            buttons,
            default_id,
            cancel_id,
            type_,
        )


# ==================== Notification Params (v1.3.0+) ====================
# 根据官方文档: https://jade.run/guides/notification


class NotificationParams(ctypes.Structure):
    """通知参数结构体

    用于 show_notification 函数。
    支持 Windows 桌面通知。

    JadeView 1.3.0+
    参考: https://jade.run/guides/notification#数据结构
    """

    _fields_ = [
        ("summary", ctypes.c_char_p),  # 通知标题（必填字段，不能为空）
        ("body", ctypes.c_char_p),  # 通知内容（可选）
        ("icon", ctypes.c_char_p),  # 图标路径（绝对路径，可选）
        ("timeout", ctypes.c_int),  # 超时时间（毫秒，<= 0 时使用默认超时）
        ("button1", ctypes.c_char_p),  # 第一个按钮文本（可选）
        ("button2", ctypes.c_char_p),  # 第二个按钮文本（可选）
        ("text3", ctypes.c_char_p),  # 第三行文本（可选）
        ("action", ctypes.c_char_p),  # 动作参数（可选，会以 arguments 传参）
    ]

    def __init__(
        self,
        summary: Optional[bytes] = None,
        body: Optional[bytes] = None,
        icon: Optional[bytes] = None,
        timeout: int = 0,
        button1: Optional[bytes] = None,
        button2: Optional[bytes] = None,
        text3: Optional[bytes] = None,
        action: Optional[bytes] = None,
    ):
        super().__init__(
            summary,
            body,
            icon,
            timeout,
            button1,
            button2,
            text3,
            action,
        )


# ==================== Tray Menu (JadeView 2.x) ====================


class TrayMenuItemDesc(ctypes.Structure):
    """托盘菜单项描述（扁平表，用 parent_key 指向父项的 key）

    JadeView 2.x。用于 tray_set_menu_items。

    item_type: 0=NORMAL, 1=SUBMENU, 2=DIVIDER, 3=GROUP
    key: 全表唯一、非空 UTF-8（分隔线也需唯一 key）
    parent_key: NULL/空=根下子项；否则须等于某 SUBMENU/GROUP 行的 key
    """

    _fields_ = [
        ("item_type", ctypes.c_int),
        ("key", ctypes.c_char_p),
        ("label", ctypes.c_char_p),
        ("parent_key", ctypes.c_char_p),
        ("disabled", ctypes.c_int),
        ("dangerous", ctypes.c_int),
    ]

    def __init__(
        self,
        item_type: int = 0,
        key: Optional[bytes] = None,
        label: Optional[bytes] = None,
        parent_key: Optional[bytes] = None,
        disabled: int = 0,
        dangerous: int = 0,
    ):
        super().__init__(item_type, key, label, parent_key, int(disabled), int(dangerous))


# Python callback types for user code
WindowEventHandler = Callable[[int, str, str], int]
PageLoadHandler = Callable[[int, str, str], None]
FileDropHandler = Callable[[int, str, str, float, float], None]
AppReadyHandler = Callable[[int, str], int]
IPCHandler = Callable[[int, str], int]
WindowAllClosedHandler = Callable[[], int]
