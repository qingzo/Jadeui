# JadeUI v2.3 Demo

演示 JadeView v2.3.0-beta.9 适配后的新增能力：

- YAML 存储：写入、读取、列 key、清理。
- 窗口集成：skip taskbar、no activate、window level、HWND 反查 window id。
- 系统集成：文件图标、开机自启状态查询、NTP UTC 毫秒时间戳。
- 拖拽事件：底层 drag-drop 阶段事件和后端推送。
- 自定义标题栏：`jade-region-drag` 拖动区域。

## 运行

```powershell
.\.venv\Scripts\python.exe examples\v23_demo\app.py
```

`Skip Taskbar`、`No Activate`、窗口层级和拖拽行为需要手动观察；`NTP` 依赖本机网络环境。
