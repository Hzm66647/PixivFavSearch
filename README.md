# PixivFavSearch

> 本地运行、一键启动的 Pixiv 收藏搜索工具 🔍

双击一个 `.bat` 文件，自动下载绿色 Python，自动装好依赖，浏览器自动打开——**开箱即用**。

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

> **仅限 Windows**，其他系统暂不支持

1. 下载 [最新版 PixivFavSearch](https://github.com/Hzm66647/PixivFavSearch/releases) 的 zip 包，解压
2. 双击 **`启动.bat`**
3. 等待命令行窗口自动下载 Python、安装依赖
4. 浏览器自动打开 `http://127.0.0.1:8897`，开始使用！

> ⚠️ 首次启动会下载约 30MB 的便携 Python + 安装依赖，**需要联网，耗时约 1-3 分钟**。之后启动秒开。

---

## 导出你的收藏 📥

如果你有自己的 Pixiv 收藏想导入：

1. 双击 **`导出收藏.bat`**
2. 浏览器会自动弹出 Pixiv 登录页面
3. 登录你的 Pixiv 账号
4. 脚本自动抓取你的收藏，保存到 `data/` 目录
5. 之后启动服务，搜索的就是你自己的收藏了

> 🔒 **你的 Cookie 不会保存到硬盘上**，登录态只在本次会话中使用，用完即弃。

---

## 数据说明 📁

```
PixivFavSearch/
├── data/
│   ├── demo_data.json    ← 示例数据（自带，可删除）
│   ├── 你的收藏.json     ← 你自己的收藏（导出后生成）
│   └── thumbs/           ← 缩略图缓存
├── 启动.bat              ← 一键启动
├── 导出收藏.bat          ← 一键导出收藏
└── pix_search_server.py  ← 搜索服务
```

- 所有数据都在 `data/` 目录下，**删除整个文件夹不会影响程序**
- 想还原出厂状态？删掉 `data/` 和 `python/` 文件夹，重新双击 `启动.bat` 即可

---

## 代理说明 🌐

**Pixiv 在国内部分地区可能无法直接访问。**

- `启动.bat` 会自动检测能否连通 Pixiv
- 如果不通，会提示你手动开启代理（如 v2rayN、Clash 等）
- 开启代理后，程序会自动走系统代理

---

## 常见问题 ❓

详见 [FAQ.md](./FAQ.md)，包含：
- 启动后浏览器没自动打开？
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

> **Windows only**

1. Download the [latest release](https://github.com/Hzm66647/PixivFavSearch/releases) zip and extract
2. Double-click **`启动.bat`**
3. Wait for portable Python to download and dependencies to install
4. Browser opens automatically at `http://127.0.0.1:8897`

> ⚠️ First run downloads ~30MB portable Python + installs deps (1-3 min). Subsequent runs are instant.

## Export Your Bookmarks 📥

Double-click **`导出收藏.bat`** → browser opens Pixiv login → log in → bookmarks are fetched automatically. **Your cookie never touches the disk.**

## License 📄

MIT © 2026 HZm66647