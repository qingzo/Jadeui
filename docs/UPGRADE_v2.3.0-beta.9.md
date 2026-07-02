# JadeUI 升级报告：JadeView v2.2.4 -> v2.3.0-beta.9

> 目标原生版本：JadeView **v2.3.0-beta.9 (Build 26G01)**  
> 依据：官方 release 包内 `JadeView.h` 与 `beta/` 文档。  
> 官方 release：https://github.com/JadeViewDocs/JadeView/releases/tag/v2.3.0-beta.9

## 1. 版本与自动更新策略

SDK 适配边界按 JadeView API/ABI 版本划分：

- `DLL_API_VERSION = "2.3.0-beta.9"`：SDK 明确适配的 release tag，不自动跨 tag。
- `DLL_BUILD = "26G01"`：默认构建号；下载器可在同一 tag 内查询并选择最新 build。

允许自动更新：

```text
2.3.0-beta.9.26G01 -> 2.3.0-beta.9.26G02
```

不允许自动跨版本：

```text
2.2.4 -> 2.3.0-beta.9
2.3.0-beta.9 -> 2.3.0
2.3.x -> 2.4.x
```

原因：build / 修订号默认无兼容性问题；minor / major / tag 变化可能包含 ABI/API 变化，必须由 SDK 显式适配。

## 2. ABI 变化

`WebViewSettings` 未发现字段变化。

`WebViewWindowOptions` 在末尾追加两个字段：

```c
int32_t skip_taskbar;
int32_t no_activate;
```

Python 侧已在 `jadeui/core/types.py` 追加字段，并在 `Window(...)` 选项中加入默认值：

- `skip_taskbar=False`
- `no_activate=False`

## 3. 新增/调整 API

窗口相关：

- `get_window_id(hwnd)`：根据 HWND 反查 JadeView window_id。
- `get_window_hwnd(window_id)`：v2.3 起可获取所有创建方式的窗口句柄。
- `set_window_skip_taskbar(window_id, skip)`：不进任务栏 / Alt-Tab。
- `set_window_no_activate(window_id, no_activate)`：显示或点击时不抢焦点。
- `set_window_level(window_id, level)`：`topmost` / `normal` / `bottom` / `desktop`。

系统集成：

- `set_login_autostart(enable, args)`
- `get_login_autostart()`
- `get_file_icon(path, size, window_id, ttl_seconds, url_buffer, buffer_size)`
- `jade_ntp_now(ntp_server)`

YAML 存储：

- `yaml_set`
- `yaml_get`
- `yaml_set_str`
- `yaml_get_str`
- `yaml_get_all`
- `yaml_has`
- `yaml_delete`
- `yaml_clear`
- `yaml_delete_file`
- `yaml_keys`
- `yaml_len`

事件：

- `drag-drop` 的 enter/drop 阶段支持同步返回值，用于拒绝拖拽或消费 drop。

前端：

- 新增 `jade-region-drag` / `jade-region-no-drag` 自定义拖动区属性，无需 Python 初始化。

## 4. Python 封装

新增：

- `jadeui/storage.py`：`Storage` 高层封装，使用 buffer 版 YAML API，避免暴露 `CoTaskMemFree` 释放细节。

增强：

- `Window.set_skip_taskbar()`
- `Window.set_no_activate()`
- `Window.set_level()`
- `Window.get_id_from_hwnd()`
- `System.set_login_autostart()`
- `System.get_login_autostart()`
- `System.get_file_icon()`
- `System.ntp_now()`

导出：

- `Storage`
- `DLL_API_VERSION`
- `DLL_BUILD`

## 5. 验证结果

已完成：

- `python -m compileall jadeui`
- 下载 v2.3.0-beta.9 x64 DLL 到本地缓存。
- 真实 DLL 加载成功：`jadeview_version -> 2.3.0-beta.9.26G01`。
- 新增函数绑定存在性检查通过：
  - `get_window_id`
  - `set_window_skip_taskbar`
  - `set_window_no_activate`
  - `set_window_level`
  - `yaml_set`
  - `yaml_get`
  - `yaml_keys`
  - `set_login_autostart`
  - `get_file_icon`
  - `jade_ntp_now`
- YAML 存储 smoke test 通过：`set/get/keys/len/delete`。
- `System.get_file_icon()` smoke test 通过，能返回 `jade://` 资源 URL。
- 同 tag 最新 build 查询通过：`get_latest_build("2.3.0-beta.9", "x64") -> "26G01"`。

待人工/GUI 验证：

- `skip_taskbar`
- `no_activate`
- `set_window_level`
- `get_window_hwnd` + `get_window_id` 互测
- `drag-drop` enter/drop 同步拦截
- examples 全量回归
- NTP 网络时间（依赖 UDP 网络，不适合作为稳定必过测试）

## 6. 注意事项

- YAML API 需要在 `JadeView_init` 完成且 data directory 就绪后使用；建议放在 `app.on_ready` 之后调用。
- `yaml_get_str` 返回 `CoTaskMemAlloc` 指针，本 SDK 高层封装暂不暴露该释放细节。
- v2.3.0-beta.9 是 prerelease，后续稳定版或其它 beta tag 不应自动跨过去。
