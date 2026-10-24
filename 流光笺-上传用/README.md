# 流光笺

一款 Windows 桌面端的轻量待办工具：记下今天要做的事，关掉窗口它还在后台，鼠标移到屏幕边缘就能看到。

**这是我第一次和 AI 一起做出来的、真正能运行的软件。** 从一句"想要个简单的待办工具"，到文档、代码、打包成 exe，全程四天。存进 GitHub 当纪念。

---

## 功能

- **今日任务**：打开就是今天，任务按时间升序排好
- **增删改**：标题、日期、时间、优先级（低 / 普通 / 高）
- **完成状态**：勾选后字体变淡、显示 ✓，并自动沉到列表底部
- **只在当天出现**：不是今天的任务不会来打扰你
- **搜索**：按关键词翻历史任务
- **悬浮窗**：默认显示今日任务，可置顶 / 置底，靠边隐藏
  - 双击任务直接完成或删除
  - 右键弹出菜单（绿色「✓ 完成」/ 红色「✕ 删除」）
  - 「⋯」按钮可以就地新建任务，不用回到主窗口
- **两套主题**：浅色 / 深色，深色配 DWM 亚克力毛玻璃效果
- **本地存储**：SQLite，不联网、不依赖任何云服务
- **后台常驻**：关掉主窗口，进程还在（系统托盘）

## 技术栈

| 部分 | 用了什么 |
|---|---|
| 语言 | Python **3.14** |
| 界面 | **CustomTkinter**（圆角、深色、亚克力） |
| 数据 | SQLite |
| 图像 / 音效 | Pillow、winsound |
| 托盘 | pystray |
| 打包 | PyInstaller（onedir 模式） |

> 一个诚实的备注：`docs/tech-stack.md` 里最初写的是 **PySide6**，实际动手后换成了 CustomTkinter —— 因为要的圆角和毛玻璃它做得更轻。文档没回去改，正好留下了当初的想法。

## 项目结构

```
流光笺/
├── app/
│   ├── main.py        # 入口
│   ├── ui.py          # 全部界面（2007 行，主力）
│   ├── storage.py     # SQLite 读写
│   ├── models.py      # 任务数据结构
│   └── config.py      # 配置读写
├── data/              # 运行时数据（config.json + tasks.db）
├── docs/
│   ├── requirements.md     # 需求说明
│   ├── tech-stack.md       # 技术方案
│   ├── design-spec.md      # 设计规范
│   └── development-steps.md# 开发步骤
├── dev-logs/          # 每日开发日志
├── tests/             # 单元测试
├── tools/             # 开发辅助脚本
├── 启动流光笺.bat
└── 流光笺.spec        # PyInstaller 打包配置
```

约 **2400 行** Python。

## 怎么跑

**方式一：源码运行**

```bash
pip install customtkinter pystray pillow darkdetect
python -m app.main
```

（`启动流光笺.bat` 里写的是一个绝对路径的 Python 解释器，换机器要改。）

**方式二：打包**

```bash
pyinstaller 流光笺.spec
```

产物在 `dist/` 下。

## 开发过程

`dev-logs/` 里留了两天的逐条记录，包括当天踩的坑。摘一条真实教训：

> customtkinter 的 `CTkFrame` 内部会调用 `_draw(no_color_updates=True)`，
> 自定义子类需避免方法名冲突。

两天里做的事包括：把顶部布局改成侧边栏、给所有卡片加 `corner_radius` 圆角、自己写 `TimePicker`（`HH : MM` 强制冒号分隔）和 `DatePicker`（三列滚轮、自动校验每月天数）、给悬浮窗加右键菜单、字体和行高来回调了三次。

## 还没做完的

写在 `dev-logs/2026-07-08.md` 的待办里，留着以后：

- 悬浮窗靠边自动隐藏
- 系统托盘后台运行（pystray 已引入，未接完）
- 日历周视图 / 月视图
- 任务置顶
- 深色模式下悬浮窗配色同步

---

*2026 年 7 月，第一次和 AI 一起做软件。*
