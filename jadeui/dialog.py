"""
JadeUI Dialog API

对话框 API，提供文件选择、保存和消息框功能。
类似 Electron 的 dialog 模块。

JadeView 1.3.0+
参考文档: https://jade.run/guides/dialog-api

同时支持前端 JavaScript 调用和 Python 后端调用：

Frontend Example (JavaScript):
    // 打开文件对话框
    const result = await jade.dialog.showOpenDialog({
        title: '选择文件',
        filters: [
            { name: '图片', extensions: ['png', 'jpg'] },
            { name: '所有文件', extensions: ['*'] }
        ],
        properties: ['openFile', 'multiSelections']
    });

    // 消息框
    const response = await jade.dialog.showMessageBox({
        title: '确认',
        message: '是否删除？',
        type: 'warning',
        buttons: ['删除', '取消']
    });

Python Example:
    from jadeui import Dialog

    # 打开文件对话框（阻塞模式）
    Dialog.show_open_dialog(
        window_id=1,
        title="选择文件",
        filters=[{"name": "图片", "extensions": ["png", "jpg"]}],
        properties=["openFile", "multiSelections"],
        blocking=True
    )

    # 消息框
    Dialog.show_message_box(
        window_id=1,
        title="确认",
        message="是否删除文件？",
        buttons=["删除", "取消"],
        type_="warning"
    )
"""

from __future__ import annotations

import ctypes
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from .core import DLLManager
from .core.types import (
    DialogCallback,
    FileDialogParams,
    MessageBoxParams,
)

logger = logging.getLogger(__name__)


def _read_result_ptr(ptr: Optional[int]) -> Optional[str]:
    """读取原生返回的 char* 结果并释放其内存。

    JadeView 2.x 的同步对话框函数返回 char*（结果 JSON 字符串），
    需调用 jade_text_free 释放。绑定层 restype 为 c_void_p，这里拿到整数地址。
    """
    if not ptr:
        return None
    try:
        text = ctypes.cast(ptr, ctypes.c_char_p).value
        result = text.decode("utf-8") if text else None
    finally:
        dll = DLLManager()
        if dll.has_function("jade_text_free"):
            try:
                dll.jade_text_free(ctypes.cast(ptr, ctypes.c_char_p))
            except Exception as e:  # pragma: no cover - 防御性
                logger.debug(f"jade_text_free failed: {e}")
    return result


def _parse_result(text: Optional[str]) -> Any:
    """尝试将结果字符串解析为 JSON；失败则原样返回。"""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


class Dialog:
    """对话框 API

    提供文件选择、保存和消息框功能。
    所有方法都是静态方法，可以直接调用。

    JadeView 1.3.0+
    参考: https://jade.run/guides/dialog-api
    """

    # 保存回调引用，防止被垃圾回收
    _callbacks: List[Any] = []

    @staticmethod
    def _format_filters_json(filters: Optional[List[Dict[str, Any]]]) -> Optional[bytes]:
        """格式化文件过滤器为 JSON 格式

        Args:
            filters: 过滤器列表，每项为 {"name": "名称", "extensions": ["ext1", "ext2"]}

        Returns:
            JSON 格式的过滤器字符串
        """
        if not filters:
            return None
        return json.dumps(filters, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _format_properties(properties: Optional[List[str]]) -> Optional[bytes]:
        """格式化对话框属性为 JSON 数组（JadeView 2.x）

        Args:
            properties: 属性列表，如 ["openFile", "multiSelections"]

        Returns:
            JSON 数组格式的属性字符串
        """
        if not properties:
            return None
        return json.dumps(properties, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def show_open_dialog(
        window_id: int = 0,
        title: Optional[str] = None,
        default_path: Optional[str] = None,
        button_label: Optional[str] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
        properties: Optional[List[str]] = None,
        blocking: bool = True,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """显示打开文件对话框

        JadeView 2.x 行为:
            - 未提供 ``callback``：同步阻塞，**返回解析后的结果**（dict/list/str），
              取消时通常为 None 或包含 ``canceled`` 字段。
            - 提供 ``callback``：异步非阻塞，结果通过回调返回，本方法返回是否成功提交 (1/0)。

        Args:
            window_id: 父窗口 ID
            title: 对话框标题
            default_path: 默认打开路径
            button_label: 确认按钮的自定义标签
            filters: 文件过滤器列表，JSON 格式
                    如 [{"name": "图片", "extensions": ["png", "jpg"]}]
            properties: 对话框属性列表
                    可选值: "openFile", "openDirectory", "multiSelections", "showHiddenFiles"
            blocking: 兼容参数；提供 callback 时按异步处理
            callback: 回调函数（异步模式），接收解析后的结果

        Example:
            # 同步：直接拿到结果
            result = Dialog.show_open_dialog(
                title="选择图片",
                filters=[{"name": "图片", "extensions": ["png", "jpg", "gif"]}],
                properties=["openFile", "multiSelections"],
            )

            # 异步 + 回调
            Dialog.show_open_dialog(properties=["openFile"], callback=lambda r: print(r))
        """
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()

        if not dll.has_function("jade_dialog_show_open_dialog"):
            logger.warning("jade_dialog_show_open_dialog 不可用，需要 JadeView 2.x")
            return None

        params = FileDialogParams(
            window_id=window_id,
            title=title.encode("utf-8") if title else None,
            default_path=default_path.encode("utf-8") if default_path else None,
            button_label=button_label.encode("utf-8") if button_label else None,
            filters=Dialog._format_filters_json(filters),
            properties=Dialog._format_properties(properties),
        )

        if callback is not None:
            return Dialog._call_async(
                "jade_dialog_show_open_dialog_async", params, callback
            )

        ptr = dll.jade_dialog_show_open_dialog(ctypes.byref(params))
        return _parse_result(_read_result_ptr(ptr))

    @staticmethod
    def show_save_dialog(
        window_id: int = 0,
        title: Optional[str] = None,
        default_path: Optional[str] = None,
        button_label: Optional[str] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
        blocking: bool = True,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """显示保存文件对话框

        JadeView 2.x 行为同 :meth:`show_open_dialog`：未提供 callback 时同步返回结果，
        提供 callback 时异步并返回提交状态。

        Args:
            window_id: 父窗口 ID
            title: 对话框标题
            default_path: 默认保存路径/文件名
            button_label: 确认按钮的自定义标签
            filters: 文件过滤器列表，JSON 格式
            blocking: 兼容参数
            callback: 回调函数（异步模式）

        Example:
            path = Dialog.show_save_dialog(
                title="保存文档",
                default_path="document.txt",
                filters=[{"name": "文本文件", "extensions": ["txt"]}],
            )
        """
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()

        if not dll.has_function("jade_dialog_show_save_dialog"):
            logger.warning("jade_dialog_show_save_dialog 不可用，需要 JadeView 2.x")
            return None

        params = FileDialogParams(
            window_id=window_id,
            title=title.encode("utf-8") if title else None,
            default_path=default_path.encode("utf-8") if default_path else None,
            button_label=button_label.encode("utf-8") if button_label else None,
            filters=Dialog._format_filters_json(filters),
            properties=None,
        )

        if callback is not None:
            return Dialog._call_async(
                "jade_dialog_show_save_dialog_async", params, callback
            )

        ptr = dll.jade_dialog_show_save_dialog(ctypes.byref(params))
        return _parse_result(_read_result_ptr(ptr))

    @staticmethod
    def show_message_box(
        window_id: int = 0,
        title: Optional[str] = None,
        message: Optional[str] = None,
        detail: Optional[str] = None,
        buttons: Optional[List[str]] = None,
        default_id: int = 0,
        cancel_id: int = -1,
        type_: str = "none",
        blocking: bool = True,
        callback: Optional[Callable[[Any], None]] = None,
    ) -> Any:
        """显示消息框

        JadeView 2.x 行为:
            - 未提供 ``callback``：同步阻塞，返回解析后的结果（通常含被点击按钮索引）。
            - 提供 ``callback``：异步非阻塞，返回提交状态 (1/0)。

        注意: ``buttons`` 现在以 JSON 数组传给底层（1.x 为 ``|`` 分隔）。

        Args:
            window_id: 父窗口 ID
            title: 消息框标题
            message: 消息内容
            detail: 详细信息（可选）
            buttons: 按钮文本列表，如 ["确定", "取消"]
            default_id: 默认选中的按钮索引
            cancel_id: 取消按钮的索引（按 ESC 时触发）
            type_: 消息类型: "none", "info", "warning", "error"
            blocking: 兼容参数
            callback: 回调函数（异步模式）

        Example:
            result = Dialog.show_message_box(
                title="确认删除",
                message="确定要删除这个文件吗？",
                detail="此操作不可撤销",
                type_="warning",
                buttons=["删除", "取消"],
                default_id=1,
                cancel_id=1,
            )
        """
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()

        if not dll.has_function("jade_dialog_show_message_box"):
            logger.warning("jade_dialog_show_message_box 不可用，需要 JadeView 2.x")
            return None

        # 格式化按钮（JadeView 2.x: JSON 数组）
        buttons_json = json.dumps(buttons or ["确定"], ensure_ascii=False)

        params = MessageBoxParams(
            window_id=window_id,
            title=title.encode("utf-8") if title else None,
            message=message.encode("utf-8") if message else None,
            detail=detail.encode("utf-8") if detail else None,
            buttons=buttons_json.encode("utf-8"),
            default_id=default_id,
            cancel_id=cancel_id,
            type_=type_.encode("utf-8") if type_ else b"none",
        )

        if callback is not None:
            return Dialog._call_async(
                "jade_dialog_show_message_box_async", params, callback
            )

        ptr = dll.jade_dialog_show_message_box(ctypes.byref(params))
        return _parse_result(_read_result_ptr(ptr))

    @staticmethod
    def _call_async(fn_name: str, params: Any, callback: Callable[[Any], None]) -> int:
        """以异步方式调用对话框函数，回调收到解析后的结果。"""
        dll = DLLManager()
        if not dll.has_function(fn_name):
            logger.warning(f"{fn_name} 不可用，需要 JadeView 2.x")
            return 0

        @DialogCallback
        def c_callback(result: bytes):
            try:
                result_str = result.decode("utf-8") if result else None
                callback(_parse_result(result_str))
            except Exception as e:
                logger.error(f"Dialog callback error: {e}")

        # 保存引用，防止回调被垃圾回收
        Dialog._callbacks.append(c_callback)
        return getattr(dll, fn_name)(ctypes.byref(params), ctypes.cast(c_callback, ctypes.c_void_p))

    @staticmethod
    def show_error_box(
        window_id: int = 0,
        title: str = "错误",
        content: str = "",
    ) -> int:
        """显示错误框

        简化的错误消息框，只有标题和内容。

        Args:
            window_id: 父窗口 ID
            title: 错误标题
            content: 错误内容

        Returns:
            1 表示成功，0 表示失败

        Example:
            Dialog.show_error_box(1, "错误", "文件读取失败！")
        """
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()

        if not dll.has_function("jade_dialog_show_error_box"):
            logger.warning("jade_dialog_show_error_box 不可用，需要 JadeView 1.3.0+")
            return 0

        result = dll.jade_dialog_show_error_box(
            window_id,
            title.encode("utf-8"),
            content.encode("utf-8"),
        )
        return result

    # ==================== 便捷方法 ====================

    @staticmethod
    def confirm(
        message: str,
        title: str = "确认",
        ok_label: str = "确定",
        cancel_label: str = "取消",
        window_id: int = 0,
    ) -> int:
        """显示确认对话框

        Args:
            message: 消息内容
            title: 对话框标题
            ok_label: 确认按钮文本
            cancel_label: 取消按钮文本
            window_id: 父窗口 ID

        Returns:
            1 表示成功调用

        Example:
            Dialog.confirm("确定要退出吗？")
        """
        return Dialog.show_message_box(
            window_id=window_id,
            title=title,
            message=message,
            type_="question",
            buttons=[ok_label, cancel_label],
            default_id=0,
            cancel_id=1,
        )

    @staticmethod
    def alert(
        message: str,
        title: str = "提示",
        type_: str = "info",
        window_id: int = 0,
    ) -> int:
        """显示提示对话框

        Args:
            message: 消息内容
            title: 对话框标题
            type_: 消息类型 ("info", "warning", "error")
            window_id: 父窗口 ID

        Returns:
            1 表示成功调用

        Example:
            Dialog.alert("操作成功！")
            Dialog.alert("请注意！", type_="warning")
        """
        return Dialog.show_message_box(
            window_id=window_id,
            title=title,
            message=message,
            type_=type_,
            buttons=["确定"],
        )

    @staticmethod
    def error(message: str, title: str = "错误", window_id: int = 0) -> int:
        """显示错误对话框

        Args:
            message: 错误消息
            title: 对话框标题
            window_id: 父窗口 ID

        Returns:
            1 表示成功调用

        Example:
            Dialog.error("文件保存失败！")
        """
        return Dialog.show_error_box(window_id, title, message)


# 保留旧的常量以保持向后兼容
class MessageBoxType:
    """消息框类型（已弃用，请使用字符串类型）"""

    NONE = "none"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    QUESTION = "question"


class OpenDialogProperties:
    """打开对话框属性（已弃用，请使用字符串列表）"""

    OPEN_FILE = "openFile"
    OPEN_DIRECTORY = "openDirectory"
    MULTI_SELECTIONS = "multiSelections"
    SHOW_HIDDEN_FILES = "showHiddenFiles"
