# JadeUI 升级报告：原生 ABI v1.3.0 → JadeView v2.2.4

> 依据：JadeView **v2.2.4 (Build 26F01)** 发布包内的权威头文件 `JadeView.h`（21.7KB），
> 而非仓库 `include/JadeView.h`（14.7KB，已过时）。
> 官方仓库：https://github.com/JadeViewDocs/JadeView （发布版在此）。

## 0. 结论

这是一次**重大破坏性升级**，不是补丁级更新。当前 fork（`jadeui` 1.3.0）按 3 参数 `JadeView_init`
和旧版结构体布局编写，**直接换用 v2.2.4 DLL 会崩溃或内存错乱**（stdcall 栈不平衡 / 结构体读到垃圾值）。
必须先完成 P0 的 ABI 对齐，应用才能启动。

升级分四档优先级：
- **P0 致命**：不改就崩溃 / 静默内存损坏。
- **P1 错误绑定**：函数名/签名错误，功能静默失效（部分在旧版就已失效）。
- **P2 基础设施**：仓库地址、下载命名、版本号。
- **P3 新能力**：v2.2.4 大量新增原生函数，可选暴露。

---

## 1. P0 — 致命 ABI 破坏性变更（必须修）

### 1.1 `JadeView_init` 参数从 3 个 → 6 个
```c
// 旧 (fork 假设)
int32_t JadeView_init(int32_t enable_devtools, const char* log_path, const char* data_directory);
// 新 v2.2.4
int32_t JadeView_init(int32_t enable_devmod, const char* log_path, const char* data_directory,
                      const char* app_name, const char* app_signature, int32_t single_instance);
```
- 这是 **required** 函数，stdcall 调用约定下参数个数不符会导致栈不平衡。
- 影响：`jadeui/core/dll.py`（绑定）、`jadeui/app.py:177-178`（调用点）。
- 新增语义：`app_name`/`app_signature`（JAPK 签名包配套，可传 NULL）、`single_instance`（单实例，配合 `second-instance` 事件）。

### 1.2 `WebViewWindowOptions` 结构体布局变化
| 旧 fork 字段 | v2.2.4 字段 | 说明 |
|---|---|---|
| `remove_titlebar` (int) + `borderless` (int) | **`frame_style` (const char\*)** | 合并为单字段："normal" / "no-titlebar" / "borderless" |
| `background_color` (**RGBA 结构体, 16字节**) | **`background_color` (const char\*)** | 改为十六进制字符串指针 `"#RRGGBBAA"` |
| `no_center` (int) | **(删除)** | 不再有该字段 |
| — | **`auto_save_state` (int)** | 末尾新增：自动保存窗口状态 |

- 这是最危险的一处：`background_color` 由 16 字节内联结构体变为 8 字节指针，且字段增删，
  导致整块结构体偏移全部错位 → 传入旧结构体 = 原生层读到垃圾值/崩溃。
- 影响：`jadeui/core/types.py:77-169`（结构体定义）、`jadeui/window.py:1338-1380`（构造点）、
  `jadeui/router.py:248`、`window.py:181-256`（remove_titlebar/borderless/no_center 相关逻辑与冲突检测全部要重写）。
- `RGBA` 结构体在窗口选项中**不再使用**（仍可保留给其它用途，但默认背景色需改为生成 hex 字符串）。

### 1.3 `WebViewSettings` 结构体新增 6 字段 + 1 字段语义反转
v2.2.4 顺序（13 字段）：
```
autoplay, background_throttling, allow_right_click, ua, preload_js,
allow_fullscreen, postmessage_whitelist, cors_whitelist, autofill,
general_autofill_enabled, incognito, disable_clipboard, proxy_url, focused
```
- `disable_right_click` → **`allow_right_click`**：不仅改名，**语义反转**（旧 1=禁用；新 1=允许）。
- 新增：`cors_whitelist`、`autofill`、`general_autofill_enabled`、`incognito`、`disable_clipboard`、`proxy_url`、`focused`。
- 影响：`jadeui/core/types.py:172-207`，以及所有构造 `WebViewSettings` 的上层默认值。

### 1.4 对话框 API 重构（结构体 + 返回类型 + 同步/异步拆分）
```c
// 统一结构体（不再分 Open/Save，且无 blocking / callback 字段）
typedef struct FileDialogParams {
  uint32_t window_id; const char* title; const char* default_path;
  const char* button_label; const char* filters; const char* properties;
} FileDialogParams;

// 同步：返回 char*（结果 JSON 字符串，需 jade_text_free），不再是 int
char* jade_dialog_show_open_dialog(const FileDialogParams* params);
char* jade_dialog_show_save_dialog(const FileDialogParams* params);
char* jade_dialog_show_message_box(const MessageBoxParams* params);
// 异步：独立函数，callback 作为显式参数
int32_t jade_dialog_show_open_dialog_async(const FileDialogParams* params, void(*cb)(const char*));
int32_t jade_dialog_show_save_dialog_async(const FileDialogParams* params, void(*cb)(const char*));
int32_t jade_dialog_show_message_box_async(const MessageBoxParams* params, void(*cb)(const char*));
```
- `MessageBoxParams` 去掉了 `blocking`、`callback` 字段；`buttons` 改为 **JSON 格式**（旧 fork 用 `|` 分隔，见 `dialog.py:336`）。
- 同步函数返回 `char*` 结果而非 1/0，需要按指针读取并 `jade_text_free` 释放。
- 影响：`jadeui/core/types.py:217-352`（OpenDialogParams/SaveDialogParams 合并为 FileDialogParams）、
  `jadeui/core/dll.py:355-388`（restype 改 c_void_p/c_char_p、签名调整、补 `_async`）、
  `jadeui/dialog.py` 整体重写（同步取返回值、异步走 `_async`、buttons 改 JSON）。

### 1.5 `navigate_to_url` 新增第 3 参数
```c
int32_t navigate_to_url(uint32_t window_id, const char* url, const char* headers_json);
```
- 影响：`jadeui/core/dll.py:280-284`、`jadeui/window.py:1147`。可传 NULL 保持旧行为。

### 1.6 `create_local_server` 被移除，改名 `set_protocol_service_path`
```c
// 旧：create_local_server(root_path, appname, url_buffer, buffer_size)
// 新：去掉 appname，新增 hot_reload（热重载，仅文件系统模式有效）
int32_t set_protocol_service_path(const char* root_path, char* url_buffer,
                                  size_t buffer_size, int32_t hot_reload);
```
- 旧函数不存在 → fork 的 `LocalServer` 会落到 no-op stub，本地服务**静默失效**。
- 影响：`jadeui/core/dll.py:228-233`、`jadeui/server.py:44-99`（去掉 app_name 入参或保留为兼容签名）。

### 1.7c `set_notification_app_registry` 已移除（运行时发现）⚠️
v2.2.4 头文件中**只剩 `show_notification`**，`set_notification_app_registry` 不存在——
通知应用注册已并入 `JadeView_init(app_name)`。
- 现象：旧 `notification.py._do_register()` 调用该函数 → 返回不可用 → 通知发不出（`显示结果: False`）。
- 修复：该函数不存在时（v2.2.4）直接视为已注册，放行到 `show_notification`；旧 DLL 仍走显式注册。
- 已运行时验证：简单/带按钮/定时通知均正常显示，`notification-shown` / `notification-dismissed` 事件正常。

### 1.7b `app_signature` 现为必填（运行时才暴露的关键点）⚠️
仅看头文件看不出来，实跑才发现：v2.2.4 的 `JadeView_init` **要求 `app_signature` 非空且为合法 UTF-8**。
传 NULL 时 `init` 返回 0，且 `app-ready` 事件报 `missing_app_signature: app_signature must be non-null and valid UTF-8`。
- 本次修复：`app.py` 在未显式提供时，将 `app_signature` 默认回退为 `app_name`。
- 另外 `app-ready` 事件数据已变为 JSON（`{"ok":true,"message":"success"}`），旧代码只匹配纯文本 `"success"`，
  会错误地走 `error` 分支；已改为 JSON 解析 + 纯文本回退。

### 1.7 `cleanup_all_windows` 废弃 → `jadeview_exit`
- `cleanup_all_windows` 仍存在但标注 `[已废弃]`，应迁移到 `jadeview_exit()`。非致命，但建议一并改。
- 影响：`jadeui/core/dll.py:191-192`、`jadeui/app.py`（退出/清理路径）。

---

## 2. P1 — 错误的函数绑定（部分在旧版即已失效）

以下绑定的函数名/签名与权威头文件不符，会被 `DLLManager.__getattr__` 兜底成 no-op stub（静默失效）：

| fork 绑定 (dll.py) | 正确名称/签名 (v2.2.4) | 后果 |
|---|---|---|
| `reload` (line 290) | `reload_webview_window(u32)` | 刷新页面静默失效 |
| `focus_window` (line 326) | `set_window_focus(u32)` | 设置焦点静默失效 |
| `get_window_theme` 带 `(u32, char*, size_t)` (line 273) | `get_window_theme(u32) -> int`（1=Dark, 0=Light） | 签名错误，读主题失效 |

> 这三处即便不升级、在旧 DLL 上也大概率是坏的。升级时一并修正。

此外，fork 里这些"窗口状态查询/设置"绑定（`is_window_minimized/visible/focused/fullscreen`、
`set_window_resizable/min_size/max_size`）在旧 14.7KB 头文件里并不存在、一直是 stub，
但在 **v2.2.4 头文件里全部真实存在**——升级后它们会真正可用，应纳入回归测试。

---

## 3. P2 — 基础设施修正（downloader / 版本 / 打包）

### 3.1 仓库地址错误
`jadeui/downloader.py:21` → `GITHUB_REPO = "JadeViewDocs/library"`，该仓库**没有任何 release**。
正确应为 **`JadeViewDocs/JadeView`**。

### 3.2 发布包命名规则变化
- 旧 fork 期望：`JadeView_win_{arch}_{static|dynamic}_v{version}.zip`，内含 `JadeView_{arch}_static.dll`，外层带同名子目录。
- v2.2.4 实际：
  - 包名：`JadeView_win_{arch}_v2.2.4.26F01.zip`（**版本含构建号 `2.2.4.26F01`，且不再有 static/dynamic 之分**）。
  - 包内（**根目录无子文件夹**）：`JadeView_{arch}.dll`、`JadeView_{arch}.lib`、`JadeView.h`。
  - DLL 文件名为 `JadeView_x64.dll`（**不带 `_static` 后缀**）。
- 需要改写 `downloader.py` 的：`DLL_VERSION`、`LINK_TYPE`（整套移除）、`get_dll_filename`、
  `get_dist_dir_name`、`get_download_url`、解压后查找逻辑，以及 `core/dll.py:_find_dll` 的搜索路径。
- 建议：版本号与构建号拆成两个常量（如 `DLL_VERSION="2.2.4"` + `DLL_BUILD="26F01"`），下载 URL 用 `v2.2.4` tag。

### 3.3 包内版本对齐
- `pyproject.toml`、`jadeui/__init__.py:__version__`、`uv.lock` 当前为 `1.3.0`，需提升（建议跳到 `2.x` 与原生大版本对齐，或在 README 标注"对应 JadeView 2.2.4"）。
- 可用新函数 `jadeview_version(buffer, size)` 在运行时校验 DLL 实际版本，做兼容性提示。

---

## 4. P3 — v2.2.4 新增原生能力（可选暴露为新 Python API）

权威头文件相比旧版多出大量函数，建议按需分批封装：

- **窗口增强**：`set_webview_zoom`(缩放)、`set_content_protection`(动态防截图)、`set_window_enabled`、
  `request_redraw`、`set_window_background_color`、`set_window_frame_style`、`set_titlebar_overlay_style`(自定义标题栏覆盖层)、
  `set_window_ignore_cursor_events`(鼠标穿透)、`get_window_bounds`、`get_window_hwnd` + `create_borderless_webview_window`(可拿原生 HWND)。
- **窗口状态查询**（升级后真实可用）：`is_window_minimized/visible/focused/fullscreen`、`set_window_min_size/max_size/resizable`。
- **系统托盘**：`tray_create/destroy/set_visible/set_tooltip/set_icon_from_file/set_menu_items/set_tray_icon_from_data` + `TrayMenuItemDesc` 结构体 + `tray-event`/`tray-menu-command` 事件。
- **原生菜单/右键菜单**：`jade_menu_item_create/set_enabled/set_checked/destroy`、`jade_set_context_menu_items` + `menu-item-clicked`/`context-menu` 事件。
- **全局热键**：`register_global_hotkey/unregister_global_hotkey` + `global-hotkey` 事件。
- **JAPK 签名/加密资源包**：`JadeView_set_public_key`、`JadeView_load_from_bytes`、`JadeView_is_loaded`、`JadeView_get_app_signature`、`JadeView_get_signature_info`、`JadeView_unload`（配合 init 的 app_name/app_signature）。
- **DevTools**：`open_devtools/close_devtools/is_devtools_open`。
- **剪贴板**：`clipboard_read_text/clipboard_write_text`。
- **打印**：`jade_print`、`jade_print_dialog`、`jade_get_printer_list`。
- **系统信息**：`get_displays_info`(多显示器)、`getLocale`(系统语言)、`getPath`(系统路径)、`get_cursor_position`、`is_windows_11`。
- **协议/关联**：`register_url_scheme/unregister_url_scheme`、`register_file_association/unregister_file_association`。
- **安全资源**：`register_resource`(本地文件→ `jade://` URL)、`unregister_resource`、`clear_window_resources`。
- **其它**：`smart_convert_encoding`(智能转码)、`yaml_set/yaml_get`(配置)、`clear_data_directory`、`clear_browsing_data`、
  `show_about_dialog`、`set_window_progress`(任务栏进度)、`flash_window`(任务栏闪烁)、`get_webview_url`。

### 新增事件（值得在 `window.py` 的事件提取器表中补充）
`context-menu`、`crash`(带详细崩溃码)、`drag-drop`(可能取代旧 file-drop)、`global-hotkey`、`japk-load-failed`、
`menu-item-clicked`、`notification-action/dismissed/shown/failed`、`postmessage-received`、`second-instance`、
`theme-changed`、`tray-event`、`tray-menu-command`、`update-window-icon`、
`webview-did-finish-load`、`webview-did-start-loading`、`webview-download-completed`、
`webview-page-favicon-updated`、`webview-page-title-updated`、
`window-blurred/bounds/closed/created/destroyed/focused/fullscreen/moved/resized/state-changed`。

### 4.1 已封装并验证的 P3 Python API（本次实现）
| 模块 | 类/方法 | 状态 |
|---|---|---|
| `jadeui/clipboard.py` | `Clipboard.read_text/write_text` | ✅ 运行时验证（中文往返） |
| `jadeui/system.py` | `System.is_windows_11/locale/displays/cursor_position/get_path/webview_version/jadeview_version` | ✅ 运行时验证 |
| `jadeui/hotkey.py` | `HotKey.register/unregister` + 组合键解析 ("Ctrl+Shift+A") | ✅ 注册验证 |
| `jadeui/tray.py` | `Tray`（图标/提示/菜单/点击事件） | ✅ 运行时验证（图标/提示/菜单/点击） |
| `jadeui/window.py` | `set_zoom/set_content_protection/set_enabled/request_redraw/set_background_color/set_frame_style/get_bounds/get_hwnd/set_ignore_cursor_events/set_progress/flash/open_devtools/close_devtools/is_devtools_open/get_current_url/clear_browsing_data/print_page/set_titlebar_overlay` | ✅ 运行时验证 |
| `jadeui/menu.py` | `Menu`（原生/右键菜单） | ⚠️ **实验性**：`jade_menu_item_create` 在测试环境返回 0，疑似官方文档未公开的前置条件 |

绑定层 `core/dll.py` 已绑定全部 32 个 P3 原生函数（含打印、URL 协议/文件关联、`jade://` 安全资源等），尚未全部封装为高层 API，可后续补充。

> 注意：`set_window_progress(window_id, progress, state)` 的 `state` 用 Windows ITaskbarList3 语义（0 无进度 / 2 正常 / 4 错误 / 8 暂停）；`Window.set_progress` 在 progress>0 时默认用 2。

---

## 4.2 ⚠️ 前端 `jade.*` Bridge API 破坏性变更（运行时实测，对 PR 关键）

v2.x 注入到 WebView 的前端 API 与 1.x 不同。实测 `Object.keys(jade)` =
**`["invoke", "invokeBatch", "on", "dialog"]`**。

| 1.x 用法 | v2.x 状态 | 正确替代 |
|---|---|---|
| `jade.ipcSend(ch, payload)` 发送到后端 | ❌ **已移除**（调用静默无效） | `jade.invoke(ch, payload)` |
| `jade.invoke(ch, 回调函数)` 订阅后端推送 | ❌ 不再是订阅语义 | `jade.on(ch, 回调)` |
| `jade.invoke(ch, payload)` 请求/响应 | ✅ 正常 | — |
| 后端 `ipc.send()` → 前端 `jade.on(ch, cb)` 推送 | ✅ 正常 | — |

**另一关键点（数据形态）**：`jade.invoke` 的**返回值**与 `jade.on` 回调收到的**推送数据**，
在 v2.x 都可能是**已解析的对象**而非 JSON 字符串。对其再 `JSON.parse()` 会抛异常。
前端务必兼容两种形态：
```js
const obj = (typeof data === 'string') ? JSON.parse(data) : data;
```

**文件拖放事件改名（运行时实测）**：原生事件 `file-drop` → **`drag-drop`**，数据格式变为
`{"type":"enter|over|drop|leave","paths":[...],"x","y"}`（路径字段 `files`→`paths`，新增阶段 `type`）。
已修 `window.py`：注册 `drag-drop`、按新格式解析、仅在 `drop` 阶段触发兼容的 `file-drop` 回调
（`@window.on_file_dropped` 无需改动），并额外暴露底层 `drag-drop` 事件。已运行时验证拖放可用。

**本次已修复的相关位置**：
- SDK 内部：`window.py` 的 `execute_js(callback=...)`（用 `jade.ipcSend` 回传 JS 结果 → 改 `jade.invoke`，否则带回调的 JS 执行在 v2.x 全坏）
- `router.py` 生成模板：`jade.ipcSend`→`jade.invoke`、订阅 `jade.invoke(ch,cb)`→`jade.on(ch,cb)`、`JSON.parse(data)` 加对象兼容
- `examples/router_demo`（3 个静态页）与 `examples/vue_app`（main.js）同步修正
- 已运行时验证：router_demo 导航 + 仪表盘/用户数据加载全部正常

---

## 5. 受影响文件清单（按改动量）

| 文件 | 改动 | 档级 |
|---|---|---|
| `jadeui/core/types.py` | WebViewWindowOptions / WebViewSettings / 对话框结构体全部重写 | P0 |
| `jadeui/core/dll.py` | init 6 参、navigate 3 参、dialog restype/签名、server 改名、修正 reload/focus/theme、补新函数 | P0/P1 |
| `jadeui/app.py` | `JadeView_init` 调用点补 3 个新参数、退出迁移 `jadeview_exit` | P0 |
| `jadeui/window.py` | background_color→hex、frame_style 合并、删 no_center、navigate 补参、事件表补充 | P0 |
| `jadeui/dialog.py` | 同步取返回值、异步走 `_async`、buttons 改 JSON | P0 |
| `jadeui/server.py` | `create_local_server` → `set_protocol_service_path`（去 appname，加 hot_reload） | P0 |
| `jadeui/router.py` | `remove_titlebar=True` → `frame_style="no-titlebar"` | P0 |
| `jadeui/downloader.py` | 仓库地址、命名规则、版本/构建号、解压查找 | P2 |
| `jadeui/notification.py` | 结构体兼容（基本一致，timeout 语义注释更新；通知事件可选接入） | P1 |
| `pyproject.toml` / `__init__.py` / `uv.lock` | 版本号 | P2 |
| `README.md` / `examples/*` | 文档与示例对齐新 API | P2 |

---

## 6. 建议的升级顺序

1. **先对齐底层 ABI（P0）**：`types.py` 结构体 → `dll.py` 绑定 → `app.py` init 调用。先让最简示例能启动不崩。
2. **修 P1 错误绑定**：reload / focus / theme，并启用真实的窗口状态查询函数。
3. **逐个模块对齐**：dialog → server → router → window 事件。
4. **修基础设施（P2）**：downloader 指向 `JadeViewDocs/JadeView`、命名规则、版本号。
5. **回归验证**：跑 `examples/` 全部示例（simple/calculator/backdrop/router/ipc/dialog_notification/fullscreen/vue）。
6. **再考虑 P3 新能力**：托盘 / 菜单 / 热键 / 剪贴板等，作为新版本卖点分批加入。
7. 重新打包（Nuitka）验证体积与依赖，更新 README 对应版本，提交上游 PR。

## 7. 风险与注意

- **stdcall + ctypes**：结构体字段一字节错位即整体崩溃，改 `types.py` 后务必逐字段比对头文件，并用最简窗口冒烟测试。
- 仓库 `include/JadeView.h`(14.7KB) 与发布包头文件(21.7KB)**不一致**——以**发布包内**头文件为准。
- 字符串返回值（dialog、version、各 get_* buffer 函数）注意 `jade_text_free` 释放，避免内存泄漏。
- 前端 JS 侧 `jade.*` API 可能也有同步变化（本报告聚焦原生 C ABI），上线前需对照官网 JS 文档另行核对。
- 建议保留对旧 DLL 的"优雅降级"（`has_function` 检测），便于过渡期兼容。
