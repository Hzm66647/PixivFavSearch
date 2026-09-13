#!/usr/bin/env python3
"""
PixivFavSearch Desktop — 增强版桌面主入口
新增: 显示/隐藏窗口切换、托盘气泡提示、草稿设置支持
"""
import os, sys, multiprocessing, threading, json
import atexit
import ctypes

if __name__ == "__main__":
    multiprocessing.freeze_support()

# 确保能 import 到同级模块
_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# Single instance check
_mutex = ctypes.windll.kernel32.CreateMutexW(None, 1, "PixivFavSearch_SingleInstance")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    print("PixivFavSearch is already running!")
    sys.exit(0)

import webview
from PIL import Image, ImageDraw, ImageFont
from pystray import Icon, Menu, MenuItem

import pix_search_server as server
import pixiv_export as exporter
import gui_worker

# 全局状态
_webview_proc = None
_webview_visible = False
_tray_icon = None

# 配置文件路径
def _get_config_path():
    """获取配置文件路径（优先本地，否则程序目录）"""
    app_data = os.environ.get("APPDATA", os.path.expanduser("~"))
    config_dir = os.path.join(app_data, "PixivFavSearch")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")

# 草稿设置
_draft_settings = {}

def _load_draft():
    """加载草稿设置"""
    global _draft_settings
    config_path = _get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _draft_settings = json.load(f)
        except:
            _draft_settings = {}

def _save_draft():
    """保存草稿设置"""
    config_path = _get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(_draft_settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存草稿失败: {e}")

# 首次使用检测
def _cookies_exist():
    return os.path.exists(exporter.COOKIE_FILE)

def _is_first_run():
    return not _cookies_exist()

# ----------------------------------------------------------------------
# GUI 子进程
# ----------------------------------------------------------------------
def _start_webview(url=None):
    """启动 WebView2 窗口"""
    global _webview_proc
    if _webview_proc is not None and _webview_proc.is_alive():
        return
    port = server.PORT
    if url is None:
        if _is_first_run():
            url = f"http://127.0.0.1:{port}/first-run"
        else:
            url = f"http://127.0.0.1:{port}/"
    _webview_proc = multiprocessing.Process(target=gui_worker.start, args=(url,), daemon=True)
    _webview_proc.start()

def _stop_webview():
    """停止 WebView2 窗口"""
    global _webview_proc
    if _webview_proc is not None and _webview_proc.is_alive():
        _webview_proc.terminate()
        _webview_proc.join(timeout=3)

# ----------------------------------------------------------------------
# 托盘回调
# ----------------------------------------------------------------------
def _on_toggle(icon, item):
    """显示/隐藏窗口"""
    global _webview_visible
    if _webview_visible:
        _stop_webview()
        _webview_visible = False
        _update_menu()
    else:
        port = server.PORT
        if _cookies_exist():
            _start_webview(f"http://127.0.0.1:{port}/")
        else:
            _start_webview(f"http://127.0.0.1:{port}/first-run")
        _webview_visible = True
        _update_menu()

def _on_export(icon, item):
    """导出收藏"""
    def run():
        try:
            code = exporter.main()
            if code == 0 and _tray_icon:
                _tray_icon.notify("导出完成！", "PixivFavSearch")
            elif _tray_icon:
                _tray_icon.notify("导出失败，请检查日志", "PixivFavSearch")
        except Exception as e:
            if _tray_icon:
                _tray_icon.notify(f"导出失败: {e}", "PixivFavSearch")
    t = threading.Thread(target=run, daemon=True)
    t.start()

def _on_settings(icon, item):
    """打开设置"""
    port = server.PORT
    _start_webview(f"http://127.0.0.1:{port}/#settings")

def _on_exit(icon, item):
    """退出程序"""
    global _webview_proc
    if _webview_proc is not None and _webview_proc.is_alive():
        _webview_proc.terminate()
        _webview_proc.join(timeout=3)
    server.stop_server()
    icon.stop()

def _update_menu():
    """更新托盘菜单（动态切换显示/隐藏）"""
    global _tray_icon, _webview_visible
    if _tray_icon is None:
        return
    _tray_icon.menu = Menu(
        MenuItem("隐藏窗口" if _webview_visible else "显示窗口", _on_toggle),
        MenuItem("导入/更新收藏", _on_export),
        MenuItem("设置", _on_settings),
        Menu.SEPARATOR,
        MenuItem("退出", _on_exit),
    )

# ----------------------------------------------------------------------
# 托盘图标
# ----------------------------------------------------------------------
def _make_tray_image():
    """生成圆角正方形紫色渐变 P 图标"""
    try:
        s = 64
        r = int(s * 0.22)
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(s):
            t = y / (s - 1)
            red = int(199 + (105 - 199) * t)
            grn = int(125 + (45 - 125) * t)
            blu = int(255 + (150 - 255) * t)
            for x in range(s):
                in_corner = False
                for cx, cy in [(r, r), (s-1-r, r), (r, s-1-r), (s-1-r, s-1-r)]:
                    if abs(x-cx) < r and abs(y-cy) < r:
                        if (x-cx)**2 + (y-cy)**2 > r**2:
                            in_corner = True
                            break
                if not in_corner:
                    d.point((x, y), fill=(red, grn, blu, 255))
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

# ----------------------------------------------------------------------
# 主函数
# ----------------------------------------------------------------------
def main():
    global _tray_icon
    
    # 加载配置
    _load_draft()
    
    # 启动 HTTP 服务
    server.start_server(host="127.0.0.1")
    port = server.PORT
    print(f"[OK] 服务已启动: http://127.0.0.1:{port}/", flush=True)
    print(f"[INFO] 首次使用: {_is_first_run()}", flush=True)
    
    # 首次启动自动打开主界面
    _start_webview()
    
    # 托盘图标
    _tray_icon = Icon("pixivfavsearch", _make_tray_image(), "PixivFavSearch", Menu(
        MenuItem("显示窗口", _on_toggle),
        MenuItem("导入/更新收藏", _on_export),
        MenuItem("设置", _on_settings),
        Menu.SEPARATOR,
        MenuItem("退出", _on_exit),
    ))
    
    # 托盘主循环
    _tray_icon.run()

if __name__ == "__main__":
    main()
