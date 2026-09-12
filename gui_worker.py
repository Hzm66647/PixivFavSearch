#!/usr/bin/env python3
"""GUI subprocess entry point — WebView2 with cookie persistence"""
import os
import multiprocessing

# WebView2 remote debugging port
local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
webview2_data = os.path.join(local_appdata, "PixivFavSearch", "WebView2Data")
os.makedirs(webview2_data, exist_ok=True)

# Cookie persistence: ensure User Data Dir is properly set
# This allows WebView2 to save cookies across sessions
os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
    '--remote-debugging-port=9223 '
    '--remote-allow-origins=* '
    f'--user-data-dir="{webview2_data}"'
    '--disable-features=msSmartScreenProtection '  # Avoid SmartScreen blocking
)

import webview

_WIN_W, _WIN_H = 1180, 800

# First-run login URL — used when no cookies detected
PIXIV_LOGIN_URL = "https://www.pixiv.net/login.php"

def start(url, title="PixivFavSearch"):
    """启动 WebView2 窗口
    
    Args:
        url: 要加载的 URL
        title: 窗口标题
    """
    webview.create_window(
        title,
        url,
        width=_WIN_W, height=_WIN_H,
        min_size=(820, 560),
        background_color="#15151a",
    )
    webview.start()

def start_login():
    """启动 WebView2 登录窗口（用于首次引导）"""
    webview.create_window(
        "PixivFavSearch — 登录 Pixiv",
        PIXIV_LOGIN_URL,
        width=500, height=700,
        min_size=(400, 600),
        background_color="#15151a",
    )
    webview.start()

def check_webview2_cookies():
    """检查 WebView2 是否有 Pixiv cookie（通过 CDP 9223）
    
    Returns:
        tuple: (has_cookies: bool, cookie_count: int)
    """
    try:
        import json
        import http.client
        
        conn = http.client.HTTPConnection("127.0.0.1", 9223, timeout=2)
        conn.request("GET", "/json")
        resp = conn.getresponse()
        targets = json.loads(resp.read())
        conn.close()
        
        page = next((t for t in targets if t.get("type") == "page"), None)
        if not page:
            return False, 0
        
        ws_url = page.get("webSocketDebuggerUrl")
        if not ws_url:
            return False, 0
        
        import websocket
        ws = websocket.create_connection(ws_url, timeout=5,
            http_proxy_host=None, http_proxy_port=None, http_no_proxy=["*"])
        
        import random
        mid = random.randint(1, 999999)
        ws.send(json.dumps({"id": mid, "method": "Network.getAllCookies"}))
        
        result = None
        while True:
            r = json.loads(ws.recv())
            if r.get("id") == mid:
                result = r
                break
        
        ws.close()
        
        if not result or "result" not in result:
            return False, 0
        
        all_c = result["result"].get("cookies", [])
        pixiv_c = [c for c in all_c if "pixiv" in c.get("domain", "")]
        return len(pixiv_c) > 0, len(pixiv_c)
        
    except Exception:
        return False, 0

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--login":
        start_login()
    else:
        start("http://127.0.0.1:8897/")
