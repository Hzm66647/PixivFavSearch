import os, sys, ctypes, subprocess, urllib.request, webbrowser
import ctypes.wintypes

def check_webview2():
    """检查 WebView2 Runtime 是否安装"""
    try:
        import winreg
        # 64-bit
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
            r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
        version, _ = winreg.QueryValueEx(key, 'pv')
        winreg.CloseKey(key)
        return True, version
    except:
        pass
    
    try:
        # 32-bit
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
            r'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}')
        version, _ = winreg.QueryValueEx(key, 'pv')
        winreg.CloseKey(key)
        return True, version
    except:
        pass
    
    # 检查 Evergreen standalone
    local_appdata = os.environ.get('LOCALAPPDATA', '')
    webview2_path = os.path.join(local_appdata, 'Microsoft', 'EdgeWebView', 'Application')
    if os.path.exists(webview2_path):
        try:
            versions = sorted(os.listdir(webview2_path), reverse=True)
            if versions:
                return True, versions[0]
        except:
            pass
    
    return False, None


def check_vcredist():
    """检查 VC++ Runtime 是否安装"""
    try:
        import winreg
        # VC++ 2015-2022 Redistributable (x64)
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')
        installed, _ = winreg.QueryValueEx(key, 'Installed')
        winreg.CloseKey(key)
        return installed == 1
    except:
        pass
    
    return True  # 如果检测不到，PyInstaller 自带


def check_windows():
    """检查 Windows 版本是否支持"""
    version = sys.getwindowsversion()
    # Windows 10 1809 (build 17763) 或更高
    return version.major >= 10 and version.build >= 17763


def check_proxy():
    """检查是否有代理可用"""
    try:
        proxies = urllib.request.getproxies()
        return 'http' in proxies or 'https' in proxies
    except:
        return False


def open_download_page(url):
    """打开下载页面"""
    try:
        webbrowser.open(url)
    except:
        pass


def install_webview2():
    """引导安装 WebView2"""
    msg = """WebView2 Runtime 未安装。

这是 PixivFavSearch 必需的系统组件，用于显示内置浏览器。

点击确定将打开微软官方下载页面。
下载并安装后请重启程序。

是否现在安装？"""
    
    result = ctypes.windll.user32.MessageBoxW(
        0, msg, "需要 WebView2 Runtime", 
        0x00000001 | 0x00000010 | 0x00010000  # MB_OKCANCEL | MB_ICONWARNING | MB_SYSTEMMODAL
    )
    
    if result == 1:  # IDOK
        # Evergreen Bootstrapper（小型安装器，自动下载完整版）
        bootstrapper_url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
        open_download_page(bootstrapper_url)


def show_welcome():
    """首次运行欢迎消息"""
    msg = """欢迎使用 PixivFavSearch！

即将打开登录页面，请在浏览器中登录 Pixiv 账号。
登录完成后程序会自动抓取你的收藏数据。

提示：
- 需要稳定的网络连接（建议开启代理）
- 首次导入可能需要几分钟，取决于收藏数量
- 后续可通过托盘菜单手动更新

点击确定继续..."""
    
    result = ctypes.windll.user32.MessageBoxW(
        0, msg, "PixivFavSearch 首次使用", 
        0x00000001 | 0x00000040 | 0x00010000  # MB_OKCANCEL | MB_ICONINFORMATION | MB_SYSTEMMODAL
    )
    
    return result == 1  # IDOK


def ensure_dependencies():
    """确保所有依赖都已满足，返回 (是否就绪, 消息列表)"""
    messages = []
    ready = True
    
    # 检查 Windows 版本
    if not check_windows():
        messages.append("❌ Windows 版本过低，需要 Windows 10 或更高版本")
        ready = False
    else:
        messages.append("✓ Windows 版本支持")
    
    # 检查 WebView2
    wv2_ok, wv2_ver = check_webview2()
    if not wv2_ok:
        messages.append("❌ WebView2 Runtime 未安装（必需）")
        ready = False
        install_webview2()
    else:
        messages.append(f"✓ WebView2 Runtime {wv2_ver}")
    
    # 检查 VC++
    if check_vcredist():
        messages.append("✓ VC++ Runtime 已安装")
    else:
        messages.append("⚠ VC++ Runtime 未检测到（PyInstaller 自带，通常无需安装）")
    
    # 检查代理
    if check_proxy():
        messages.append("✓ 检测到代理设置")
    else:
        messages.append("ℹ 未检测到代理（访问 Pixiv 可能需要代理）")
    
    return ready, messages


if __name__ == "__main__":
    print("检查系统依赖...")
    ready, messages = ensure_dependencies()
    for msg in messages:
        print(f"  {msg}")
    
    if ready:
        print("\n✓ 系统检查通过")
    else:
        print("\n✗ 系统检查未通过")
