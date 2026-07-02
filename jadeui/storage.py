"""
JadeUI YAML Storage

High-level wrapper for JadeView 2.3 YAML persistence APIs.
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


def _b(value: str) -> bytes:
    return value.encode("utf-8")


def _payload(value: Any, force_string: bool = False) -> bytes:
    if force_string:
        return str(value).encode("utf-8")
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _read_json_buffer(fn_name: str, *args: bytes) -> Optional[Any]:
    dll = _dll()
    if not dll.has_function(fn_name):
        logger.warning(f"{fn_name} 不可用，需要 JadeView 2.3+")
        return None

    fn = getattr(dll, fn_name)
    needed = fn(*args, None, 0)
    if needed == 0:
        return None
    if needed < 0:
        logger.debug(f"{fn_name} failed with code {needed}")
        return None

    size = max(int(needed), 1024)
    buf = ctypes.create_string_buffer(size)
    result = fn(*args, buf, size)
    if result != 1:
        logger.debug(f"{fn_name} failed with code {result}")
        return None

    text = buf.value.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


class Storage:
    """YAML-backed key/value storage under JadeView ``data_directory``."""

    @staticmethod
    def set(file_name: str, key_path: str, value: Any) -> bool:
        """Set a value. Strings may be parsed by JadeView as YAML/JSON scalars."""
        dll = _dll()
        if not dll.has_function("yaml_set"):
            logger.warning("yaml_set 不可用，需要 JadeView 2.3+")
            return False
        return dll.yaml_set(_b(file_name), _b(key_path), _payload(value)) == 1

    @staticmethod
    def set_str(file_name: str, key_path: str, value: Any) -> bool:
        """Set a value as a literal string without YAML/JSON parsing."""
        dll = _dll()
        if not dll.has_function("yaml_set_str"):
            logger.warning("yaml_set_str 不可用，需要 JadeView 2.3+")
            return False
        return dll.yaml_set_str(_b(file_name), _b(key_path), _payload(value, True)) == 1

    @staticmethod
    def get(file_name: str, key_path: str, default: Any = None) -> Any:
        """Get a value from ``file_name`` at ``key_path``."""
        value = _read_json_buffer("yaml_get", _b(file_name), _b(key_path))
        return default if value is None else value

    @staticmethod
    def get_all(file_name: str, default: Any = None) -> Any:
        """Read the entire YAML file as a Python value."""
        value = _read_json_buffer("yaml_get_all", _b(file_name))
        return default if value is None else value

    @staticmethod
    def has(file_name: str, key_path: str) -> bool:
        """Return whether a path exists."""
        dll = _dll()
        if not dll.has_function("yaml_has"):
            return False
        return dll.yaml_has(_b(file_name), _b(key_path)) == 1

    @staticmethod
    def delete(file_name: str, key_path: str) -> bool:
        """Delete a path from a YAML file."""
        dll = _dll()
        if not dll.has_function("yaml_delete"):
            return False
        return dll.yaml_delete(_b(file_name), _b(key_path)) == 1

    @staticmethod
    def clear(file_name: str) -> bool:
        """Clear a YAML file to an empty mapping."""
        dll = _dll()
        if not dll.has_function("yaml_clear"):
            return False
        return dll.yaml_clear(_b(file_name)) == 1

    @staticmethod
    def delete_file(file_name: str) -> bool:
        """Delete a YAML data file."""
        dll = _dll()
        if not dll.has_function("yaml_delete_file"):
            return False
        return dll.yaml_delete_file(_b(file_name)) == 1

    @staticmethod
    def keys(file_name: str, key_path: str = "") -> List[Any]:
        """List keys or indices under a path."""
        value = _read_json_buffer("yaml_keys", _b(file_name), _b(key_path))
        return value if isinstance(value, list) else []

    @staticmethod
    def len(file_name: str, key_path: str = "") -> int:
        """Return object key count or array length. Missing/non-container returns 0."""
        dll = _dll()
        if not dll.has_function("yaml_len"):
            return 0
        result = int(dll.yaml_len(_b(file_name), _b(key_path)))
        return result if result >= 0 else 0

    length = len
