"""
JadeUI Clipboard API

系统剪贴板读写 (JadeView 2.x)。

Example:
    from jadeui import Clipboard

    Clipboard.write_text("hello")
    print(Clipboard.read_text())
"""

from __future__ import annotations

import ctypes
import logging
from typing import Optional

from .core import DLLManager

logger = logging.getLogger(__name__)


class Clipboard:
    """系统剪贴板（纯文本）

    JadeView 2.x。所有方法均为静态方法。
    """

    @staticmethod
    def _dll() -> DLLManager:
        dll = DLLManager()
        if not dll.is_loaded():
            dll.load()
        return dll

    @staticmethod
    def write_text(text: str) -> bool:
        """写入文本到剪贴板

        Args:
            text: 要写入的文本

        Returns:
            成功返回 True
        """
        dll = Clipboard._dll()
        if not dll.has_function("clipboard_write_text"):
            logger.warning("clipboard_write_text 不可用，需要 JadeView 2.x")
            return False
        return dll.clipboard_write_text(text.encode("utf-8")) == 1

    @staticmethod
    def read_text(buffer_size: int = 1 << 16) -> Optional[str]:
        """读取剪贴板文本

        Args:
            buffer_size: 读取缓冲区大小（字节），默认 64KB

        Returns:
            剪贴板文本；为空或失败时返回 None
        """
        dll = Clipboard._dll()
        if not dll.has_function("clipboard_read_text"):
            logger.warning("clipboard_read_text 不可用，需要 JadeView 2.x")
            return None
        buf = ctypes.create_string_buffer(buffer_size)
        result = dll.clipboard_read_text(buf, buffer_size)
        if result <= 0:
            return None
        return buf.value.decode("utf-8", "replace")
