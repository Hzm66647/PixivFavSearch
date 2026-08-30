#!/usr/bin/env python3
"""PixivFavSearch 收藏导出器 (CDP Network.loadNetworkResource, 最优方案)

方案优先级:
  A. CDP loadNetworkResource (浏览器网络栈, 支持公开+私密, 零代理问题)
  B. CDP 浏览器内fetch (备选)
  C. CDP读cookie + Python urllib (兜底)
"""
import os, sys, json, re, time, socket, subprocess, urllib.request, urllib.parse, platform

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
SETTINGS = os.path.join(OUT, "settings.json")
os.makedirs(OUT, exist_ok=True)

PORT = int(os.environ.get("CDP_PORT", "9222"))
PIXIV = "https://www.pixiv.net/bookmark.php?rest=show"

_DEBUG = os.environ.get("PIXIV_DEBUG", "0") == "1"

_stat = {"retry_count": 0, "total_backoff": 0.0, "pages_fetched": 0, "pages_failed": 0}

def _log(tag, msg):
    print(f"[{tag}] {msg}", flush=True)

def _err_type(e):
    if isinstance(e, socket.timeout) or "timed out" in str(e).lower(): return "TIMEOUT"
    if isinstance(e, ConnectionRefusedError) or "10061" in str(e): return "REFUSED"
    if "10054" in str(e) or "reset" in str(e).lower(): return "RESET"
    if "10051" in str(e) or "unreachable" in str(e).lower(): return "UNREACHABLE"
    if "10060" in str(e): return "TIMEOUT"
    if "10065" in str(e): return "HOST_UNREACHABLE"
    if "remote end closed" in str(e).lower() or "connection aborted" in str(e).lower(): return "PROXY_RESET"
    if "name resolution" in str(e).lower() or "getaddrinfo" in str(e).lower(): return "DNS_FAIL"
    if "ssl" in str(e).lower() or "certificate" in str(e).lower(): return "TLS_FAIL"
    if isinstance(e, urllib.error.HTTPError): return f"HTTP_{e.code}"
    return f"OTHER:{type(e).__name__}"

_NO_PROXY = urllib.request.ProxyHandler({})
_LOCAL_OPENER = urllib.request.build_opener(_NO_PROXY)

try:
    from websocket import create_connection
except ImportError:
    print("缺少 websocket-client")
    sys.exit(1)

def cdp_targets():
    try:
        with _LOCAL_OPENER.open(f"http://127.0.0.1:{PORT}/json", timeout=3) as r:
            return json.loads(r.read())
    except:
        return None

_EDGE_PATHS = [
    r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
]

def _launch_edge(profile_dir=None, headless=False):
    """启动调试 Edge, 可指定 profile 目录复用登录态"""
    edge = next((p for p in _EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        return False
    args = [edge, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check"]
    if profile_dir:
        args.append(f"--profile-directory={profile_dir}")
    else:
        args.append(f"--user-data-dir={os.path.join(APP_DATA, 'edge_profile')}")
    args.append(PIXIV)
    p = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for i in range(30):
        time.sleep(1)
        if cdp_targets():
            return True
    return False

def _load_settings():
    if os.path.exists(SETTINGS):
        try:
            with open(SETTINGS, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def _save_settings(settings):
    try:
        with open(SETTINGS, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except:
        pass

def _get_user_default_edge_profile():
    """获取用户默认 Edge profile 目录"""
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    user_data = os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
    if os.path.exists(os.path.join(user_data, "Default")):
        return "Default"
    return None

# ══════════════════════════════════════════════════════════════
# 方案 A: CDP Network.loadNetworkResource (最优)
# ══════════════════════════════════════════════════════════════
def _fetch_via_load_resource(pages, uid):
    """用 CDP Network.loadNetworkResource 走浏览器网络栈, 支持公开+私密"""
    _log("main", "[方案A] 尝试 CDP Network.loadNetworkResource...")
    
    # 找 pixiv tab 或任意可用 tab
    target = None
    for p in pages:
        if p.get("type") in ("page", "other") and "pixiv" in p.get("url", ""):
            target = p
            break
    if not target:
        for p in pages:
            if p.get("type") in ("page", "other"):
                target = p
                break
    
    if not target:
        _log("main", "[方案A] 无可用 tab")
        return None, "NO_TAB"
    
    ws_url = target["webSocketDebuggerUrl"]
    ws = create_connection(ws_url, timeout=60)
    _id = 0
    def cdp(method, params=None, timeout=60):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        ws.settimeout(timeout)
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id:
                return msg.get("result", {})
    
    # 导航到 rest=show 页面 (提供 frame 上下文, 不要导航到 rest=hide)
    cdp("Page.enable")
    current_url = target.get("url", "")
    if "rest=show" not in current_url and "rest=hide" not in current_url:
        _log("main", f"[方案A] 导航到 rest=show 页面...")
        cdp("Page.navigate", {"url": f"https://www.pixiv.net/users/{uid}/bookmarks/artworks?rest=show"})
        time.sleep(6)  # SPA 加载
    
    # 获取 frameId
    frame_tree = cdp("Page.getFrameTree")
    frame_id = frame_tree.get("frameTree", {}).get("frame", {}).get("id")
    if not frame_id:
        ws.close()
        return None, "NO_FRAME", False
    
    def ajax(url):
        """用 loadNetworkResource 读 AJAX 响应"""
        res = cdp("Network.loadNetworkResource", {
            "frameId": frame_id,
            "url": url,
            "options": {"disableCache": False, "includeCredentials": True}
        })["resource"]
        stream = res.get("stream")
        if not stream:
            return None, res.get("httpStatusCode")
        body = ""
        while True:
            d = cdp("IO.read", {"handle": stream})
            body += d.get("data", "")
            if d.get("eof"):
                break
        return json.loads(body), 200
    
    # 先检测是否有私密收藏 (用官方 tags API)
    all_items = []
    has_private = False
    
    try:
        tags_url = f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmark/tags?lang=zh"
        tags_d, _ = ajax(tags_url)
        if tags_d and not tags_d.get("error"):
            private_tags = (tags_d.get("body") or {}).get("private") or []
            public_tags = (tags_d.get("body") or {}).get("public") or []
            _log("main", f"[方案A] 收藏统计: 公开标签 {len(public_tags)} 个, 私密标签 {len(private_tags)} 个")
            if private_tags:
                has_private = True
    except Exception as e:
        _log("main", f"[方案A] 私密标签检测失败: {_err_type(e)} {e}, 将尝试抓取私密收藏")

    # 根据检测结果决定抓取顺序
    if has_private:
        rest_order = (("hide", "PRIVATE"), ("show", "PUBLIC"))
    else:
        rest_order = (("show", "PUBLIC"),)
    
    for rest, label in rest_order:
        offset = 0
        page_num = 0
        while True:
            page_num += 1
            url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
                   f"?tag=&offset={offset}&limit=48&rest={rest}&order=desc&mode=all&lang=zh")
            try:
                d, status = ajax(url)
                if not d or d.get("error"):
                    break
                works = d.get("body", {}).get("works") or []
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
                _log("fetch", f"[方案A/{label}] 第{page_num}页: {len(works)} works (累计 {len(all_items)})")
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except Exception as e:
                _log("fetch", f"[方案A/{label}] 异常: {_err_type(e)} {e}")
                break
    
    try:
        ws.close()
    except:
        pass
    
    if all_items:
        return all_items, "OK", has_private
    return None, "EMPTY", False

# ══════════════════════════════════════════════════════════════
# 方案 B: CDP 浏览器内 fetch (备选)
# ══════════════════════════════════════════════════════════════
def _fetch_via_browser_fetch(pages, uid):
    """备选: Runtime.evaluate + fetch (可能冻结)"""
    _log("main", "[方案B] 尝试 CDP 浏览器内 fetch...")
    target = next((p for p in pages if p.get("type") in ("page", "other")), None)
    if not target:
        return None, "NO_TAB"
    
    ws = create_connection(target["webSocketDebuggerUrl"], timeout=60)
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
    
    all_items = []
    for rest in ("show", "hide"):
        offset = 0
        while True:
            url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
                   f"?tag=&offset={offset}&limit=48&rest={rest}&order=desc&mode=all&lang=zh")
            js = f"""
            (async () => {{
                try {{
                    const r = await fetch("{url}", {{credentials: "include"}});
                    const d = await r.json();
                    return JSON.stringify(d);
                }} catch(e) {{
                    return JSON.stringify({{error: true, err: e.message}});
                }}
            }})()
            """
            try:
                res = cdp("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, timeout=15)
                d = json.loads((res.get("result") or {}).get("value", "{}"))
                if d.get("error"):
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
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except:
                break
    
    try:
        ws.close()
    except:
        pass
    
    if all_items:
        return all_items, "OK", False
    return None, "EMPTY", False

# ══════════════════════════════════════════════════════════════
# 方案 C: CDP 读 cookie + Python urllib (兜底)
# ══════════════════════════════════════════════════════════════
def _fetch_via_cdp_urllib(pages, uid):
    """兜底: CDP 读 cookie + Python urllib"""
    _log("main", "[方案C] 尝试 CDP + Python urllib...")
    target = next((p for p in pages if p.get("type") in ("page", "other")), None)
    if not target:
        return None, "NO_TAB"
    
    ws = create_connection(target["webSocketDebuggerUrl"], timeout=60)
    _id = 0
    def cdp(method, params=None, timeout=60):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        ws.settimeout(timeout)
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id:
                return msg.get("result", {})
    
    cdp("Network.enable")
    r = cdp("Network.getCookies", {"urls": ["https://www.pixiv.net"]})
    cookies = r.get("cookies", [])
    phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
    
    if not phpsessid:
        ws.close()
        return None, "NO_LOGIN"
    
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    ws.close()
    
    all_items = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Referer": "https://www.pixiv.net/",
        "Cookie": cookie_header,
        "Accept": "application/json",
    }
    
    for rest in ("show",):
        offset = 0
        while True:
            url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
                   f"?tag=&offset={offset}&limit=48&rest={rest}&order=desc&mode=all&lang=zh")
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read())
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
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except Exception as e:
                break
    
    if all_items:
        return all_items, "OK", False
    return None, "EMPTY", False

# ══════════════════════════════════════════════════════════════
# uid 检测
# ══════════════════════════════════════════════════════════════
def _detect_uid(pages):
    """多来源 uid 检测"""
    uid = os.environ.get("PIXIV_UID", "")
    
    settings = _load_settings()
    if not uid:
        uid = settings.get("pixiv_uid", "")
    
    if pages:
        for p in pages:
            url = p.get("url", "")
            m = re.search(r".*/users/(\d+).*", url)
            if m:
                uid = m.group(1)
                break
    
    if not uid:
        profile = _get_user_default_edge_profile()
        if profile:
            prefs = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data", profile, "Preferences")
            if os.path.exists(prefs):
                try:
                    with open(prefs, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for c in data.get("cookies", []):
                        if c.get("name") == "yuid_b":
                            m = re.search(r"\d{4,}", c.get("value", ""))
                            if m:
                                uid = m.group(0)
                                break
                except:
                    pass
    
    return uid

def main():
    _log("main", f"=== 开始导入 (PORT={PORT}) ===")
    
    pages = cdp_targets()
    uid = _detect_uid(pages or [])
    
    if not uid:
        _log("main", "无法自动检测 uid")
        print("请在设置中填写 Pixiv 用户ID，或确保 Edge 已打开收藏页")
        return 1
    
    if not os.path.exists(SETTINGS):
        _save_settings({"pixiv_uid": uid})
    
    _log("main", f"目标 uid={uid}")
    
    # 如果无 CDP, 尝试启动用户 Edge (复用登录态)
    if not pages:
        _log("main", "无 CDP 实例, 尝试启动用户 Edge...")
        profile = _get_user_default_edge_profile()
        if profile:
            _launch_edge(profile_dir=profile)
        else:
            _launch_edge()
        pages = cdp_targets()
    
    all_items = []
    method_used = ""
    has_private = False
    
    # ── 方案 A: loadNetworkResource ──
    if pages:
        items, status, priv = _fetch_via_load_resource(pages, uid)
        if items:
            all_items = items
            has_private = priv
            method_used = "A:loadNetworkResource"
        else:
            _log("main", f"[方案A] 失败: {status}")
    
    # ── 方案 B: 浏览器内 fetch ──
    if not all_items and pages:
        items, status, priv = _fetch_via_browser_fetch(pages, uid)
        if items:
            all_items = items
            has_private = priv
            method_used = "B:browserFetch"
        else:
            _log("main", f"[方案B] 失败: {status}")
    
    # ── 方案 C: CDP + urllib ──
    if not all_items and pages:
        items, status, priv = _fetch_via_cdp_urllib(pages, uid)
        if items:
            all_items = items
            has_private = priv
            method_used = "C:cdp+urllib"
        else:
            _log("main", f"[方案C] 失败: {status}")
    
    if not all_items:
        _log("main", "所有方案均失败")
        print("导入失败。请检查:")
        print("  1. 网络连接是否正常")
        print("  2. 已在 Edge 中登录 Pixiv")
        return 1
    
    # 写入文件
    _json_data = json.dumps(all_items, ensure_ascii=False, indent=1)
    with open(DATA, "w", encoding="utf-8") as f:
        f.write(_json_data)
    
    privacy_note = " (含私密收藏)" if has_private else ""
    _log("main", f"=== 完成: 导出 {len(all_items)} 幅收藏{privacy_note} (方案: {method_used}) ===")
    print(f"[OK] 已导出 {len(all_items)} 幅收藏{privacy_note} (方案: {method_used})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
