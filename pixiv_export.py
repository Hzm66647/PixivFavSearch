#!/usr/bin/env python3
"""PixivFavSearch 导出器 - WebView2 cookies + urllib with system proxy"""
import os, sys, json, re, time, socket, urllib.request

APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
SETTINGS = os.path.join(OUT, "settings.json")
os.makedirs(OUT, exist_ok=True)

PORT = int(os.environ.get("CDP_PORT", "9222"))
_WEBVIEW2_PORT = 9223

def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)

try:
    from websocket import create_connection
except ImportError:
    print("Missing websocket-client")
    sys.exit(1)

def _get_targets(port):
    try:
        # Use system proxy for CDP connection too
        proxy_handler = urllib.request.ProxyHandler({
            'http': 'http://127.0.0.1:10808',
            'https': 'http://127.0.0.1:10808'
        })
        opener = urllib.request.build_opener(proxy_handler)
        with opener.open(f"http://127.0.0.1:{port}/json", timeout=3) as r:
            return json.loads(r.read())
    except:
        # Fallback: direct connection
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(f"http://127.0.0.1:{port}/json", timeout=3) as r:
                return json.loads(r.read())
        except:
            return None

def _detect_uid_from_cookies(cookies):
    for c in cookies:
        if c.get("name") == "yuid_b":
            m = re.search(r"\d{4,}", c.get("value", ""))
            if m:
                return m.group(0)
    return ""

def _detect_uid():
    uid = os.environ.get("PIXIV_UID", "")
    if not uid and os.path.exists(SETTINGS):
        try:
            uid = json.load(open(SETTINGS, "r", encoding="utf-8")).get("pixiv_uid", "")
        except:
            pass
    return uid

def _fetch_via_cdp_cookies(port, uid):
    """Get cookies from CDP, then fetch with urllib + proxy"""
    targets = _get_targets(port)
    if not targets:
        return None, "NO_TARGETS"
    
    target = next((t for t in targets if t.get("type") == "page"), None)
    if not target:
        return None, "NO_PAGE"
    
    ws_url = target.get("webSocketDebuggerUrl")
    if not ws_url:
        return None, "NO_WS"
    
    ws = create_connection(ws_url, timeout=120)
    _id = 0
    def cdp(method, params=None, timeout=30):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        ws.settimeout(timeout)
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id:
                return msg.get("result", {})
    
    # Bypass Service Worker
    cdp("Network.setBypassServiceWorker", {"bypass": True})
    
    # Get cookies
    cdp("Network.enable")
    r = cdp("Network.getCookies", {"urls": ["https://www.pixiv.net"]})
    cookies = r.get("cookies", [])
    
    cookie_uid = _detect_uid_from_cookies(cookies)
    if cookie_uid:
        uid = cookie_uid
    
    # No login -> navigate to login and wait
    if not cookies or not any(c["name"] == "PHPSESSID" for c in cookies):
        _log("main", f"[CDP:{port}] No pixiv cookie, navigating to login...")
        cdp("Page.navigate", {"url": "https://www.pixiv.net/login.php"})
        time.sleep(3)
        
        _log("main", f"[CDP:{port}] Waiting for login...")
        start = time.time()
        while time.time() - start < 180:
            time.sleep(3)
            try:
                res = cdp("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
                url = res.get("result", {}).get("result", {}).get("value", "")
                if "pixiv.net" in url and "login" not in url and "accounts" not in url:
                    _log("main", f"[CDP:{port}] Login success!")
                    break
            except:
                pass
        
        r = cdp("Network.getCookies", {"urls": ["https://www.pixiv.net"]})
        cookies = r.get("cookies", [])
        cookie_uid = _detect_uid_from_cookies(cookies)
        if cookie_uid:
            uid = cookie_uid
    
    if not cookies:
        ws.close()
        return None, "NO_COOKIES"
    
    phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
    if not phpsessid:
        ws.close()
        return None, "NO_PHPSESSID"
    
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    _log("main", f"[CDP:{port}] Got {len(cookies)} cookies, uid={uid}")
    ws.close()
    
    # urllib with system proxy (v2rayN on 127.0.0.1:10808)
    all_items = []
    proxy_handler = urllib.request.ProxyHandler({
        'http': 'http://127.0.0.1:10808',
        'https': 'http://127.0.0.1:10808'
    })
    opener = urllib.request.build_opener(proxy_handler)
    
    for rest in ("show", "hide"):
        offset = 0
        while True:
            ajax_url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
                       f"?tag=&offset={offset}&limit=48&rest={rest}&order=desc&mode=all&lang=zh")
            req = urllib.request.Request(ajax_url, headers={
                "Cookie": cookie_header,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
                "Referer": "https://www.pixiv.net/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            })
            try:
                with opener.open(req, timeout=30) as resp:
                    d = json.loads(resp.read())
                if d.get("error"):
                    _log("main", f"[urllib/{rest}] API error at offset {offset}")
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
                _log("main", f"[urllib/{rest}] +{len(works)} (total {len(all_items)})")
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    _log("main", f"[urllib/{rest}] 403 Forbidden (private bookmarks may need different auth)")
                else:
                    _log("main", f"[urllib/{rest}] HTTP {e.code}")
                break
            except Exception as e:
                _log("main", f"[urllib/{rest}] error: {e}")
                break
    
    if all_items:
        return all_items, "OK"
    return None, "EMPTY"

def main():
    _log("main", f"=== Import Start ===")
    
    uid = _detect_uid()
    if not uid:
        _log("main", "Cannot detect uid")
        return 1
    
    if not os.path.exists(SETTINGS):
        json.dump({"pixiv_uid": uid}, open(SETTINGS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    
    _log("main", f"Initial uid={uid}")
    
    # Try WebView2 first
    all_items, status = _fetch_via_cdp_cookies(_WEBVIEW2_PORT, uid)
    if all_items:
        method = "WebView2"
    else:
        _log("main", f"[WebView2] Failed: {status}, trying Edge...")
        all_items, status = _fetch_via_cdp_cookies(PORT, uid)
        if all_items:
            method = "Edge"
        else:
            _log("main", f"[Edge] Failed: {status}")
            print("Import failed. Please login to pixiv in WebView2 or Edge")
            return 1
    
    # Update uid from data
    if all_items and all_items[0].get("userId"):
        correct_uid = all_items[0]["userId"]
        if correct_uid != uid:
            _log("main", f"Update uid: {uid} -> {correct_uid}")
            json.dump({"pixiv_uid": correct_uid}, open(SETTINGS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    
    # Write
    json.dump(all_items, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    
    _log("main", f"=== Done: {len(all_items)} bookmarks ({method}) ===")
    print(f"[OK] Exported {len(all_items)} bookmarks")
    
    # Always navigate WebView2 (9223) back to home page (8897)
    try:
        targets = _get_targets(_WEBVIEW2_PORT)
        if targets:
            t = next((t for t in targets if t.get("type") == "page"), None)
            if t:
                ws2 = create_connection(t["webSocketDebuggerUrl"], timeout=10)
                ws2.send(json.dumps({"id":999,"method":"Page.navigate","params":{"url":"http://127.0.0.1:8897/"}}))
                ws2.settimeout(5)
                ws2.recv()
                ws2.close()
                _log("main", "WebView2: navigated back to home page")
    except:
        pass
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
