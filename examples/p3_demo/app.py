"""
JadeUI P3 能力示例 (JadeView 2.x 新增)

展示：
- System Tray  系统托盘（图标 / 提示 / 菜单）
- HotKey       全局热键（Ctrl+Alt+J）
- Clipboard    剪贴板读写
- System       系统信息（显示器 / 语言 / 路径）
- Window extras 缩放 / 开发者工具 / 任务栏进度 / 闪烁

运行:
    python examples/p3_demo/app.py
"""

import os

from jadeui import (
    Clipboard,
    HotKey,
    IPCManager,
    JadeUIApp,
    LocalServer,
    System,
    Tray,
    Window,
)

HERE = os.path.dirname(__file__)
ICON = os.path.join(HERE, "web", "tray.ico")

ipc = IPCManager()
app = JadeUIApp()

# 全局引用，避免被回收
state = {"win": None, "tray": None}


# ==================== IPC：窗口增强能力 ====================


@ipc.on("zoomIn")
def zoom_in(window_id, _):
    state["win"].set_zoom(1.3)
    return '{"ok":true}'


@ipc.on("zoomReset")
def zoom_reset(window_id, _):
    state["win"].set_zoom(1.0)
    return '{"ok":true}'


@ipc.on("toggleDevtools")
def toggle_devtools(window_id, _):
    win = state["win"]
    win.close_devtools() if win.is_devtools_open else win.open_devtools()
    return '{"ok":true}'


@ipc.on("progress")
def progress(window_id, _):
    state["win"].set_progress(66)
    return '{"ok":true}'


@ipc.on("flash")
def flash(window_id, _):
    state["win"].flash(3)
    return '{"ok":true}'


@ipc.on("clipWrite")
def clip_write(window_id, text):
    Clipboard.write_text(text or "Hello from JadeUI 2.2.4")
    return '{"ok":true}'


@ipc.on("clipRead")
def clip_read(window_id, _):
    import json

    return json.dumps({"text": Clipboard.read_text() or ""}, ensure_ascii=False)


@ipc.on("sysInfo")
def sys_info(window_id, _):
    import json

    return json.dumps(
        {
            "win11": System.is_windows_11(),
            "locale": System.locale(),
            "displays": len(System.displays()),
            "desktop": System.get_path("desktop"),
            "jadeview": System.jadeview_version(),
            "webview": System.webview_version(),
        },
        ensure_ascii=False,
    )


# ==================== app ready：托盘 + 热键 ====================


@app.on_ready
def on_ready():
    server = LocalServer()
    server_url = server.start("p3demo", os.path.join(HERE, "web"))
    win = Window(title="JadeUI P3 Demo", width=760, height=620, url=f"{server_url}/index.html")
    state["win"] = win

    # 系统托盘
    tray = Tray()
    tray.set_tooltip("JadeUI P3 Demo")
    if os.path.exists(ICON):
        tray.set_icon(ICON)
    tray.set_menu(
        [
            {"key": "show", "label": "显示窗口", "on_click": lambda: win.show()},
            {"key": "flash", "label": "任务栏闪烁", "on_click": lambda: win.flash(3)},
            {"type": "separator", "key": "sep1"},
            {"key": "quit", "label": "退出", "dangerous": True, "on_click": app.quit},
        ]
    )
    tray.show()
    state["tray"] = tray

    # 全局热键：Ctrl+Alt+J -> 闪烁任务栏
    HotKey.register("Ctrl+Alt+J", lambda: (print("[热键] Ctrl+Alt+J 触发"), win.flash(5)))

    print("[就绪] 托盘已显示，全局热键 Ctrl+Alt+J 已注册")
    print(f"[系统] Win11={System.is_windows_11()}  语言={System.locale()}  "
          f"显示器={len(System.displays())}  JadeView={System.jadeview_version()}")

    win.show()


app.run()
