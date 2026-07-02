r"""
JadeUI v2.3.0-beta.9 feature demo.

Run:
    .\.venv\Scripts\python.exe examples\v23_demo\app.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jadeui import (  # noqa: E402
    DLL_API_VERSION,
    DLL_BUILD,
    IPCManager,
    JadeUIApp,
    LocalServer,
    Storage,
    System,
    Window,
    __version__,
)


ipc = IPCManager()
app = JadeUIApp()

state: dict[str, Any] = {
    "win": None,
    "skip_taskbar": False,
    "no_activate": False,
    "level": "normal",
    "drops": [],
}


def respond(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def current_window() -> Window:
    win = state.get("win")
    if not isinstance(win, Window):
        raise RuntimeError("Window is not ready")
    return win


@ipc.on("windowAction")
def window_action(_window_id: int, action: str) -> str:
    win = current_window()
    if action == "minimize":
        win.minimize()
    elif action == "maximize":
        win.restore() if win.is_maximized else win.maximize()
    elif action == "close":
        win.close()
    return respond({"ok": True, "action": action})


@ipc.on("versionInfo")
def version_info(_window_id: int, _message: str) -> str:
    return respond(
        {
            "sdk": __version__,
            "apiVersion": DLL_API_VERSION,
            "build": DLL_BUILD,
            "jadeview": System.jadeview_version(),
            "webview": System.webview_version(),
        }
    )


@ipc.on("storageWrite")
def storage_write(_window_id: int, _message: str) -> str:
    stamp = int(time.time())
    ok_profile = Storage.set(
        "v23_demo",
        "profile",
        {
            "name": "JadeUI v2.3 demo",
            "updatedAt": stamp,
            "features": ["yaml", "window-level", "file-icon"],
        },
    )
    ok_note = Storage.set_str("v23_demo", "note", "literal string: true")
    return respond({"ok": bool(ok_profile and ok_note), "data": Storage.get_all("v23_demo", {})})


@ipc.on("storageRead")
def storage_read(_window_id: int, _message: str) -> str:
    return respond(
        {
            "data": Storage.get_all("v23_demo", {}),
            "keys": Storage.keys("v23_demo"),
            "profileKeys": Storage.keys("v23_demo", "profile"),
            "profileLen": Storage.length("v23_demo", "profile"),
            "hasNote": Storage.has("v23_demo", "note"),
        }
    )


@ipc.on("storageClear")
def storage_clear(_window_id: int, _message: str) -> str:
    return respond({"ok": Storage.delete_file("v23_demo"), "data": Storage.get_all("v23_demo", {})})


@ipc.on("hwndInfo")
def hwnd_info(_window_id: int, _message: str) -> str:
    win = current_window()
    hwnd = win.get_hwnd()
    resolved_id = Window.get_id_from_hwnd(hwnd) if hwnd else 0
    return respond({"windowId": win.id, "hwnd": hwnd, "resolvedId": resolved_id})


@ipc.on("toggleSkipTaskbar")
def toggle_skip_taskbar(_window_id: int, _message: str) -> str:
    win = current_window()
    state["skip_taskbar"] = not bool(state["skip_taskbar"])
    win.set_skip_taskbar(bool(state["skip_taskbar"]))
    return respond({"skipTaskbar": state["skip_taskbar"]})


@ipc.on("toggleNoActivate")
def toggle_no_activate(_window_id: int, _message: str) -> str:
    win = current_window()
    state["no_activate"] = not bool(state["no_activate"])
    win.set_no_activate(bool(state["no_activate"]))
    return respond({"noActivate": state["no_activate"]})


@ipc.on("setWindowLevel")
def set_window_level(_window_id: int, level: str) -> str:
    win = current_window()
    win.set_level(level)
    state["level"] = level
    return respond({"level": level})


@ipc.on("fileIcon")
def file_icon(_window_id: int, _message: str) -> str:
    win = current_window()
    icon_url = System.get_file_icon(sys.executable, size=64, window_id=win.id or 0, ttl_seconds=60)
    return respond({"python": sys.executable, "icon": icon_url})


@ipc.on("autostartStatus")
def autostart_status(_window_id: int, _message: str) -> str:
    return respond({"enabled": System.get_login_autostart()})


@ipc.on("ntpNow")
def ntp_now(_window_id: int, message: str) -> str:
    server = message.strip() or None
    return respond({"server": server or "default", "utcMs": System.ntp_now(server)})


@ipc.on("dropEvents")
def drop_events(_window_id: int, _message: str) -> str:
    return respond({"events": state["drops"][-8:]})


@app.on_ready
def on_ready() -> None:
    server = LocalServer()
    server_url = server.start("v23demo", os.path.join(HERE, "web"))

    win = Window(
        title="JadeUI v2.3 Demo",
        width=940,
        height=700,
        url=f"{server_url}/index.html",
        remove_titlebar=True,
        min_width=760,
        min_height=560,
    )
    state["win"] = win

    @win.on("drag-drop")
    def on_drag_drop(data: dict[str, Any]) -> None:
        item = {
            "type": data.get("type", "drop"),
            "paths": data.get("paths", data.get("files", [])),
            "x": data.get("x", 0),
            "y": data.get("y", 0),
        }
        state["drops"].append(item)
        if win.id is not None:
            ipc.send(win.id, "dragDropEvent", respond(item))

    print(f"[ready] JadeUI SDK {__version__}, JadeView {System.jadeview_version()}")
    win.show()


app.run()
