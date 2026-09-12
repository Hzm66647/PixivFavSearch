#!/usr/bin/env python3
"""PixivFavSearch Desktop — 桌面版主入口

架构(借鉴 pywebview 官方 pystray 示例):
  主进程: 运行 HTTP 服务(thread) + 系统托盘图标(pystray, 主循环)
  子进程: 跑 pywebview GUI 窗口(加载 http://127.0.0.1:PORT/)
  用户关闭窗口 → 子进程退出, 托盘还在, 仅从托盘右键"退出"才真正结束程序

首次使用引导: 启动时检查 cookies.json, 不存在则加载引导页
"""
import os, sys, multiprocessing, threading
import atexit

# onefile 打包下, 子进程需要 freeze_support 才能正确 fork
if __name__ == "__main__":
    multiprocessing.freeze_support()

# 确保能 import 到同级模块(onefile 解压目录 / 源码目录)
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# Single instance check - prevent multiple exe instances
import ctypes
_mutex = ctypes.windll.kernel32.CreateMutexW(None, 1, "PixivFavSearch_SingleInstance")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    print("PixivFavSearch is already running!")
    sys.exit(0)

import webview
from PIL import Image
from pystray import Icon, Menu, MenuItem

import pix_search_server as server
import pixiv_export as exporter
import gui_worker


# ----------------------------------------------------------------------
# 首次使用检测
# ----------------------------------------------------------------------
def _cookies_exist():
    """检查 cookies.json 是否存在"""
    return os.path.exists(exporter.COOKIE_FILE)

def _is_first_run():
    """是否为首次使用（无 cookie 文件）"""
    return not _cookies_exist()


# ----------------------------------------------------------------------
# GUI 子进程: pywebview (独立模块 gui_worker, PyInstaller spawn 兼容)
# ----------------------------------------------------------------------
_webview_proc = None


def _start_webview(url=None):
    """启动 WebView2 窗口
    
    Args:
        url: 自定义 URL，不传则根据首次使用状态自动选择
    """
    global _webview_proc
    if _webview_proc is not None and _webview_proc.is_alive():
        return
    port = server.PORT
    if url is None:
        # 首次使用 → 引导页，否则 → 主界面
        if _is_first_run():
            url = f"http://127.0.0.1:{port}/first-run"
        else:
            url = f"http://127.0.0.1:{port}/"
    _webview_proc = multiprocessing.Process(target=gui_worker.start, args=(url,), daemon=True)
    _webview_proc.start()


# ----------------------------------------------------------------------
# 托盘回调
# ----------------------------------------------------------------------
def _on_open(icon, item):
    """打开主界面"""
    # 如果 cookies 已被创建（首次引导完成后），直接进主界面
    # 否则进引导页
    port = server.PORT
    if _cookies_exist():
        _start_webview(f"http://127.0.0.1:{port}/")
    else:
        _start_webview(f"http://127.0.0.1:{port}/first-run")


def _on_export(icon, item):
    """导出收藏（从 cookies.json 读取，抓取最新收藏）"""
    def run():
        try:
            code = exporter.main()
            if code == 0:
                icon.notify("导出完成", "PixivFavSearch")
            else:
                # 读取错误信息
                icon.notify("导出失败，请检查 cookies.json 是否存在", "PixivFavSearch")
        except Exception as e:
            icon.notify(f"导出失败: {e}", "PixivFavSearch")
    t = threading.Thread(target=run, daemon=True)
    t.start()


def _on_import_first_run(icon, item):
    """首次使用/重新登录 — 打开引导页"""
    port = server.PORT
    _start_webview(f"http://127.0.0.1:{port}/first-run")


def _on_exit(icon, item):
    global _webview_proc
    if _webview_proc is not None and _webview_proc.is_alive():
        _webview_proc.terminate()
        _webview_proc.join(timeout=3)
    server.stop_server()
    icon.stop()


def _make_tray_image():
    """生成圆角正方形紫色渐变 P 图标(与 exe 图标一致)"""
    try:
        s = 64
        r = int(s * 0.22)  # 圆角半径
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        from PIL import ImageDraw, ImageFont
        d = ImageDraw.Draw(img)
        # 紫色渐变圆角正方形
        for y in range(s):
            t = y / (s - 1)
            red = int(199 + (105 - 199) * t)
            grn = int(125 + (45 - 125) * t)
            blu = int(255 + (150 - 255) * t)
            for x in range(s):
                # 圆角遮罩: 四个角半径内保留
                in_corner = False
                for cx, cy in [(r, r), (s-1-r, r), (r, s-1-r), (s-1-r, s-1-r)]:
                    if abs(x-cx) < r and abs(y-cy) < r:
                        if (x-cx)**2 + (y-cy)**2 > r**2:
                            in_corner = True
                            break
                if not in_corner:
                    d.point((x, y), fill=(red, grn, blu, 255))
        # 白色 P 字母
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 38)
        except Exception:
            font = ImageFont.load_default()
        bbox = d.textbbox((0, 0), "P", font=font)
        tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
        px = (s - tw) / 2 - bbox[0]
        py = (s - th) / 2 - bbox[1] + 2
        d.text((px, py), "P", fill=(255, 255, 255, 255), font=font)
        return img
    except Exception:
        return Image.new("RGBA", (64, 64), (199, 125, 255, 255))


def main():
    # 启动 HTTP 服务(线程)
    server.start_server(host="127.0.0.1")
    port = server.PORT
    print(f"[OK] 服务已启动: http://127.0.0.1:{port}/  数据目录: {server.OUT}", flush=True)
    print(f"[INFO] 首次使用: {_is_first_run()}")
    print("[INFO] 正在检查更新（WebView 中 JS 自动检查）...", flush=True)

    # 托盘图标
    menu = Menu(
        MenuItem("打开主界面", _on_open),
        MenuItem("导入/更新收藏", _on_export),
        MenuItem("重新登录 Pixiv", _on_import_first_run),
        Menu.SEPARATOR,
        MenuItem("退出", _on_exit),
    )
    icon = Icon("pixivfavsearch", _make_tray_image(), "PixivFavSearch", menu)

    # 首次启动自动打开主界面（或引导页）
    _start_webview()

    # 托盘主循环(阻塞)
    icon.run()


if __name__ == "__main__":
    main()
