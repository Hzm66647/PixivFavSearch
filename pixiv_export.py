#!/usr/bin/env python3
"""PixivFavSearch exporter v7 — Read saved cookies, fetch bookmarks via proxy

新增首次使用引导支持：
- grab_cookies_via_cdp(port): 通过 CDP 从浏览器抓取 cookie
- save_cookies(cookies): 保存 cookie 到 cookies.json
"""
import os, sys, json, re, time, urllib.request, urllib.error
import socket

APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
COOKIE_FILE = os.path.join(OUT, "cookies.json")
os.makedirs(OUT, exist_ok=True)

def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)

def _detect_uid(cookies):
    for c in cookies:
        if c.get("name") == "PHPSESSID":
            val = c.get("value", "")
            m = re.match(r"^(\d{6,})_", val)
            if m:
                return m.group(1)
    for c in cookies:
        if c.get("name") == "user_id":
            val = c.get("value", "")
            if val.isdigit() and len(val) >= 6:
                return val
    return ""

# ----------------------------------------------------------------------
# 新增：CDP cookie 抓取（供首次引导使用）
# ----------------------------------------------------------------------
def _ws_send(ws, method, params=None):
    """发送 CDP 命令并等待对应 id 的响应"""
    import random
    mid = random.randint(1, 999999)
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        try:
            r = json.loads(ws.recv())
            if r.get("id") == mid:
                return r
        except Exception:
            return None

def grab_cookies_via_cdp(port=9222, proxy_bypass=True):
    """通过 CDP 从浏览器抓取 Pixiv cookie
    
    Args:
        port: CDP 端口（Edge 用 9222，WebView2 用 9223）
        proxy_bypass: 是否绕过代理连接本地 CDP
        
    Returns:
        list: cookie 字典列表，失败返回空列表
    """
    try:
        import http.client
        import websocket
    except ImportError as e:
        _log("cdp", f"缺少依赖: {e} (需安装 websocket-client)")
        return []
    
    # 连接 CDP 获取 ws target
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/json")
        resp = conn.getresponse()
        targets = json.loads(resp.read())
        conn.close()
    except Exception as e:
        _log("cdp", f"连接 CDP 端口 {port} 失败: {e}")
        return []
    
    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        _log("cdp", f"端口 {port} 无可用 page target")
        return []
    
    ws_url = page.get("webSocketDebuggerUrl")
    if not ws_url:
        _log("cdp", "无 webSocketDebuggerUrl")
        return []
    
    # 连接 WebSocket
    try:
        ws_opts = {"timeout": 10}
        if proxy_bypass:
            ws_opts.update({
                "http_proxy_host": None,
                "http_proxy_port": None,
                "http_no_proxy": ["*"],
            })
        ws = websocket.create_connection(ws_url, **ws_opts)
    except Exception as e:
        _log("cdp", f"WebSocket 连接失败: {e}")
        return []
    
    try:
        # 先 enable Network
        _ws_send(ws, "Network.enable")
        
        # 导航到 pixiv.net 确保有 cookie
        _ws_send(ws, "Page.navigate", {"url": "https://www.pixiv.net"})
        time.sleep(3)
        
        # 获取所有 cookie
        result = _ws_send(ws, "Network.getAllCookies")
        if not result or "result" not in result:
            _log("cdp", "getAllCookies 返回空结果")
            return []
        
        all_c = result["result"].get("cookies", [])
        pixiv_cookies = [c for c in all_c if "pixiv" in c.get("domain", "") or "pximg" in c.get("domain", "")]
        
        _log("cdp", f"抓取到 {len(pixiv_cookies)} 个 Pixiv cookie")
        return pixiv_cookies
    except Exception as e:
        _log("cdp", f"抓取过程异常: {e}")
        return []
    finally:
        try:
            ws.close()
        except Exception:
            pass

def grab_cookies_from_edge():
    """从 Edge 浏览器 (CDP 9222) 抓取 Pixiv cookie"""
    return grab_cookies_via_cdp(port=9222)

def grab_cookies_from_webview():
    """从 WebView2 (CDP 9223) 抓取 Pixiv cookie"""
    return grab_cookies_via_cdp(port=9223)

def save_cookies(cookies):
    """保存 cookie 到 cookies.json
    
    Args:
        cookies: cookie 字典列表
        
    Returns:
        tuple: (success: bool, uid: str, count: int)
    """
    if not cookies:
        return False, "", 0
    
    try:
        json.dump(cookies, open(COOKIE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        uid = _detect_uid(cookies)
        return True, uid, len(cookies)
    except Exception as e:
        _log("cookie", f"保存失败: {e}")
        return False, "", 0

# ----------------------------------------------------------------------
# 原有导入逻辑（保持不变）
# ----------------------------------------------------------------------
def main():
    _log("main", "=== Import Start ===")
    
    # 1. Load saved cookies
    if not os.path.exists(COOKIE_FILE):
        _log("main", "ERROR: No saved cookies found.")
        print("ERROR: No cookies.json found.")
        return 1
    
    try:
        cookies = json.load(open(COOKIE_FILE, "r", encoding="utf-8"))
        _log("main", f"Loaded {len(cookies)} saved cookies")
    except Exception as e:
        _log("main", f"Failed to load cookies: {e}")
        return 1
    
    # 2. Detect uid
    uid = _detect_uid(cookies)
    _log("main", f"uid={uid}")
    
    if not uid:
        _log("main", "ERROR: Cannot detect uid from cookies")
        return 1
    
    # 3. Fetch bookmarks
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    
    _log("main", f"Fetching bookmarks for uid {uid}...")
    all_items = []
    
    proxy = urllib.request.ProxyHandler({
        'http': 'http://127.0.0.1:10808',
        'https': 'http://127.0.0.1:10808'
    })
    opener = urllib.request.build_opener(proxy)
    
    for rest in ("show", "hide"):
        offset = 0
        while True:
            url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
                   f"?tag=&offset={offset}&limit=48&rest={rest}&order=desc&mode=all&lang=zh")
            req = urllib.request.Request(url, headers={
                "Cookie": cookie_header,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.pixiv.net/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            })
            try:
                with opener.open(req, timeout=30) as resp:
                    d = json.loads(resp.read())
                if d.get("error"):
                    _log("main", f"[{rest}] API error: {d.get('message')}")
                    break
                works = (d.get("body") or {}).get("works") or []
                if not works:
                    break
                for w in works:
                    all_items.append({
                        "id": str(w.get("id")),
                        "title": w.get("title", ""),
                        "tags": [t.get("tag", "") if isinstance(t, dict) else str(t)
                                 for t in (w.get("tags") or [])],
                        "description": w.get("description", ""),
                        "url": w.get("url", ""),
                        "userId": str(w.get("userId", "")),
                        "userName": w.get("userName", ""),
                        "width": w.get("width"),
                        "height": w.get("height"),
                        "pageCount": w.get("pageCount"),
                        "createDate": w.get("createDate", ""),
                        "aiType": w.get("aiType"),
                    })
                _log("main", f"[{rest}] +{len(works)} (total {len(all_items)})")
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    _log("main", f"[{rest}] 403 (private)")
                else:
                    _log("main", f"[{rest}] HTTP {e.code}")
                break
            except Exception as e:
                _log("main", f"[{rest}] Error: {e}")
                break
    
    if not all_items:
        print("ERROR: No items fetched")
        return 1
    
    json.dump(all_items, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _log("main", f"=== Done: {len(all_items)} bookmarks ===")
    print(f"OK: {len(all_items)} bookmarks imported")
    return 0

if __name__ == "__main__":
    sys.exit(main())
