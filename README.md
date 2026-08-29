# PixivFavSearch

> 本地运行、一键启动的 Pixiv 收藏搜索工具 🔍

下载一个 exe，双击即用——桌面窗口打开，无需浏览器、无需安装 Python、无需配代理。**开箱即用**。

---

## 功能特性 ✨

- **全字段搜索** — 标题、标签、简介全部可搜
- **自定义收藏标签** — 你用「感受」「mvp」这些自定义标签分类，这里直接搜
- **日文假名→罗马音** — 搜 `sakura` 也能找到 `サクラ`，跨语言模糊匹配
- **中英可切换** — 界面右上角一键切换语言
- **缩略图本地缓存** — 缩略图下载到本地，下次秒开
- **DIY 封面导入** — 上传自定义图片作封面
- **撤销/重做** — Ctrl+Z 撤销上一步搜索，Ctrl+Shift+Z 重做
- **内置检查更新** — 启动时自动检查 GitHub 新版，有更新提示你
- **带示例数据** — 开箱即有演示数据，没有自己的收藏也能先体验

---

## 快速开始 🚀

> **仅限 Windows 10/11**（需 WebView2 运行时，Win11 已内置），其他系统暂不支持

1. 下载 [最新版 PixivFavSearch](https://github.com/Hzm66647/PixivFavSearch/releases) 的 **PixivFavSearch.exe**
2. **双击 exe**，等待 10-15 秒（首次解压运行时资源）
3. 桌面窗口自动弹出，开始使用！

> ⚠️ 点窗口右上角的 **× 只是把窗口收进系统托盘**（右下角图标区），不会退出程序。要彻底退出，右键托盘图标选「退出」。
>
> 🎨 启动后若显示「效果预览」横幅，说明还没导入你自己的收藏，正在用内置示例数据。导入后即可搜你自己的收藏。

---

## 导入你的收藏 📥

如果你有自己的 Pixiv 收藏想导入：

1. 打开软件，点击界面上的 **「📥 导入/更新收藏」** 按钮
2. 浏览器（或内置窗口）自动弹出 Pixiv 登录页
3. 登录你的 Pixiv 账号
4. 程序自动抓取你的收藏并保存
5. 之后搜索的就是你自己的收藏了

> 🔒 **你的 Cookie 不会保存到硬盘上**，登录态只在本次抓取会话中于内存使用，用完即弃。

> 💡 也可双击 `导出收藏.bat`（源码版/zip 包内）走同样流程。

---

## 数据说明 📁

桌面版的数据不再放在程序目录，而是统一存到 **用户数据目录**：

```
%LOCALAPPDATA%\PixivFavSearch\
├── data\
│   ├── bookmarks.json    ← 你的收藏（导入后生成）
│   └── thumbs\           ← 缩略图缓存
└── pix_assets\           ← 上传的封面图等
```

- 数据跟随 Windows 用户账号，卸载/覆盖程序不影响收藏
- 想还原出厂状态？关掉程序，删掉 `%LOCALAPPDATA%\PixivFavSearch` 文件夹即可

---

## 代理说明 🌐

**Pixiv 在国内部分地区可能无法直接访问。**

- 软件启动时自动检测能否连通 Pixiv
- 如果不通，请先开启你的代理软件（如 v2rayN、Clash）
- 开启代理后，程序会自动走系统代理

---

## 从源码编译 exe 🔨

想自己动手编译（比如改了代码）：

### 准备
- Python 3.9+（开发用 3.11）
- 安装依赖：`pip install pywebview pystray pillow pykakasi jieba PySocks requests websocket-client`

### 编译
```bat
python -m PyInstaller PixivFavSearch.spec --noconfirm --clean
```
产物在 `dist\PixivFavSearch.exe`。

### 编译要点（踩过的坑）
- `.spec` 已内置配置：**pykakasi 的字典 `.db` 文件必须手动收集**，否则 exe 启动即崩（MEI 临时目录找不到数据）——spec 里已用 `glob` 自动收集，别删
- onefile 模式，`console=False`（GUI 应用无黑窗）
- 程序图标 `icon.ico` 已在 spec 里指定
- 需要 `freeze_support`：多进程 GUI（主进程 + pywebview 子进程）在 onefile 下必须，`desktop_app.py` 已处理

---

## 常见问题 ❓

详见 [FAQ.md](./FAQ.md)，包含：
- 双击 exe 没反应/白屏？
- 搜索没结果？
- 缩略图加载不出来？
- 如何更新到新版本？
- 安全吗？我的 Cookie 会泄露吗？

---

## 许可证 📄

MIT License © 2026 HZm66647

**免责声明**：本工具仅用于个人收藏管理，请遵守 [Pixiv 服务条款](https://www.pixiv.net/terms/)。使用本工具产生的任何问题由使用者自行承担。

---

## Features ✨

- Full-text search across title, tags, and description
- Custom bookmark tag categories (coltags)
- Japanese kana → romaji cross-language search
- Switchable Chinese / English UI
- Local thumbnail cache
- DIY cover image import
- Undo / Redo (Ctrl+Z / Ctrl+Shift+Z)
- Built-in update check
- Comes with demo data — works out of the box

## Quick Start 🚀

> **Windows 10/11 only** (WebView2 required, preinstalled on Win11)

1. Download **PixivFavSearch.exe** from the [latest release](https://github.com/Hzm66647/PixivFavSearch/releases)
2. Double-click the exe, wait 10-15s on first launch
3. Desktop window opens — start searching!

> ⚠️ Clicking **× only hides the window to the system tray** (near the clock). Right-click the tray icon → "Exit" to fully quit.

## Import Your Bookmarks 📥

Click **"📥 Import / Update"** in the app → login to Pixiv when prompted → bookmarks are fetched automatically. **Your cookie never touches the disk.**

## Build from Source 🔨

```bat
pip install pywebview pystray pillow pykakasi jieba PySocks requests websocket-client
python -m PyInstaller PixivFavSearch.spec --noconfirm --clean
```

Output in `dist\PixivFavSearch.exe`. The `.spec` already handles pykakasi `.db` data files (required or the exe crashes on startup).

## License 📄

MIT © 2026 HZm66647
