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
import webbrowser
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
    # 用户点过"跳过"则不再弹引导页(直到有 cookie)
    import os as _os
    _skip = _os.path.join(_os.environ.get("LOCALAPPDATA", ""), "PixivFavSearch", ".skip_first_run")
    if _os.path.exists(_skip):
        return False
    return not _cookies_exist()

# ----------------------------------------------------------------------
# GUI 子进程
# ----------------------------------------------------------------------
_ext_win_procs = []  # 外部链接窗口(pixiv 作品页等), 关掉即回主应用

def open_external_window(url):
    """在独立 WebView2 窗口打开外部链接(备选模式)。
    供 pix_search_server 的 /api/open-work(mode=inner) 调用 ——
    应用内窗口, 关掉即回主应用。"""
    try:
        p = multiprocessing.Process(target=gui_worker.start, args=(url, url.split("/")[2][:40]), daemon=True)
        p.start()
        _ext_win_procs.append(p)
        # 清理已退出的
        for q in list(_ext_win_procs):
            if not q.is_alive():
                _ext_win_procs.remove(q)
        return True
    except Exception:
        return False

def _start_login_window():
    """拉起 WebView2 登录窗口(独立进程, 带 CDP 9223 环境)。
    供 /api/first-run/launch-login 调用 —— 纯服务器模式直接调
    gui_worker 会没有 9223 环境, cookie 抓不到。"""
    try:
        p = multiprocessing.Process(target=gui_worker.start_login, daemon=True)
        p.start()
        _ext_win_procs.append(p)
        return True
    except Exception:
        return False

def open_in_browser(url):
    """用系统默认浏览器打开链接(默认模式)。
    跳转后弹托盘气泡提示 —— 用户在浏览器里看完,
    点一下托盘图标(或气泡)即回主应用窗口。"""
    try:
        webbrowser.open(url)
        # 气泡提示: 点击托盘图标回主窗口
        try:
            if _tray_icon is not None:
                _tray_icon.notify("已在浏览器打开 · 点托盘图标返回主界面", "PixivFavSearch")
        except Exception:
            pass
        return True
    except Exception:
        return False

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
def _on_show_main(icon=None, item=None):
    """托盘左键单击: 显示主窗口(从浏览器看完作品, 点托盘一键回主应用)。"""
    global _webview_visible
    port = server.PORT
    if _webview_proc is None or not _webview_proc.is_alive():
        if _cookies_exist():
            _start_webview(f"http://127.0.0.1:{port}/")
        else:
            _start_webview(f"http://127.0.0.1:{port}/first-run")
        _webview_visible = True
        _update_menu()

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
    """导出收藏。

    必须走 server.start_import() 统一入口, 不能直接调 exporter.main():
    直接调会绕过 _import_state(前端一直显示"导入中…")、
    绕过 _IMPORT_PROG 进度回调(看不到进度)、
    绕过 reload_pixiv_if_changed()(导入完新作品不刷新)。
    """
    def run():
        try:
            if not server.start_import():
                if _tray_icon:
                    _tray_icon.notify("已有导入在进行中", "PixivFavSearch")
                return
            # 等待导入线程结束(轮询状态), 再根据结果提示
            import time as _t
            for _ in range(1800):          # 最多等 30 分钟
                _t.sleep(1)
                st = server.import_status()
                if not st.get("running"):
                    break
            else:
                if _tray_icon:
                    _tray_icon.notify("导入超时, 请查看日志", "PixivFavSearch")
                return
            st = server.import_status()
            if st.get("code") == 0:
                _n = st.get("new_count", -1)
                _tail = f"新增 {_n} 条" if _n > 0 else ("没有新收藏" if _n == 0 else "已更新")
                if _tray_icon:
                    _tray_icon.notify(f"导入完成！共 {st.get('count', 0)} 幅 · {_tail}", "PixivFavSearch")
            else:
                if _tray_icon:
                    _tray_icon.notify(f"导入失败: {st.get('msg', '请检查日志')}", "PixivFavSearch")
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
    
    # ---- 全新机器环境自检(首跑无数据时) ----
    # WebView2 Runtime 缺失 → 弹窗引导安装; 其余环境问题记日志不拦启动
    try:
        import check_deps
        if _is_first_run():
            ok_wv, ver = check_deps.check_webview2()
            if not ok_wv:
                check_deps.install_webview2()   # 弹窗引导, 用户装完重启 exe
                return                          # 没 WebView2 开窗必失败, 直接退出
            if not check_deps.check_windows():
                print("[WARN] Windows 版本过低(需 Win10 1809+), 部分功能可能异常", flush=True)
            if not check_deps.check_proxy():
                print("[WARN] 未检测到系统代理, pixiv 访问可能失败(建议开启 v2rayN/Clash)", flush=True)
            print(f"[OK] 环境自检通过: WebView2 {ver}", flush=True)
    except Exception as e:
        print(f"[WARN] 环境自检异常(不拦截启动): {e}", flush=True)
    
    # 加载配置
    _load_draft()
    
    # 注册链接打开回调(openWork 跳 pixiv 用, 避免 exe 里循环 import)
    try:
        server.register_open_window_callback(open_external_window)   # inner 模式
        server.register_browser_callback(open_in_browser)             # browser 模式(默认)
        server.register_login_callback(_start_login_window)           # 首跑登录窗口
        # 标记桌面模式: 前端据此避开 WebView2 里 window.open 空窗口
        # 触发的"获取打开此'about'链接的应用"系统对话框。
        server.set_desktop_mode(True)
    except Exception:
        pass

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
    ), default_action=_on_show_main)
    
    # 托盘主循环
    _tray_icon.run()

if __name__ == "__main__":
    main()
