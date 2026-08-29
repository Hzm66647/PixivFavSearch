#!/usr/bin/env python3
"""PixivFavSearch 收藏导出器 (多方案回退, cookie 不落盘)

抓取路径 (按优先级尝试):
  A. CDP 读已有调试浏览器 + Python urllib 直发  (主路径)
  B. CDP 浏览器内 fetch (绕过代理)
  C. 启动新调试 Edge 实例 + 自动登录流程
"""
import os, sys, json, re, time, socket, subprocess, urllib.request, urllib.parse, platform

# 可选依赖
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
        _t0 = time.time()
        with _LOCAL_OPENER.open(f"http://127.0.0.1:{PORT}/json", timeout=3) as r:
            data = json.loads(r.read())
        return data
    except Exception as e:
        return None

_EDGE_PATHS = [
    r"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
]
_EDGE_PROFILE = os.path.join(APP_DATA, "edge_profile")

def _launch_edge(headless=True):
    edge = next((p for p in _EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        return False
    os.makedirs(_EDGE_PROFILE, exist_ok=True)
    args = [edge, f"--remote-debugging-port={PORT}", "--remote-allow-origins=*",
            f"--user-data-dir={_EDGE_PROFILE}", "--no-first-run", "--no-default-browser-check"]
    if headless:
        args[3:3] = ["--headless=new", "--disable-gpu"]
    args.append(PIXIV)
    p = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for i in range(20):
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

def _detect_uid_from_edge(profile_path=None):
    """尝试从 Edge profile 的 Preferences 文件读取 uid"""
    if profile_path is None:
        profile_path = _EDGE_PROFILE
    prefs = os.path.join(profile_path, "Default", "Preferences")
    if os.path.exists(prefs):
        try:
            with open(prefs, "r", encoding="utf-8") as f:
                prefs_data = json.load(f)
            cookies = prefs_data.get("cookies", [])
            for c in cookies:
                if c.get("name") == "yuid_b":
                    m = re.search(r"\d{4,}", c.get("value", ""))
                    if m:
                        return m.group(0)
        except:
            pass
    return None

def _get_user_default_edge_profile():
    """获取用户默认 Edge 配置目录"""
    local_appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    default_profile = os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
    if os.path.exists(os.path.join(default_profile, "Default")):
        return default_profile
    return None

def _is_user_edge_running():
    """检查用户日常 Edge 是否在运行"""
    if not _HAS_PSUTIL:
        return False
    try:
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] and 'msedge' in proc.info['name'].lower():
                return True
    except:
        pass
    return False

# ══════════════════════════════════════════════════════════════
# 方案 B: CDP 浏览器内 fetch (绕过代理, 需要 CDP)
# ══════════════════════════════════════════════════════════════
def _fetch_browser_internal(ws_url, uid):
    """通过 CDP 在浏览器内部发 fetch, 绕过系统代理"""
    _log("main", "[方案B] 尝试 CDP 浏览器内 fetch")
    ws = create_connection(ws_url, timeout=30)
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
    offset = 0
    while True:
        url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
               f"?tag=&offset={offset}&limit=48&rest=show&order=desc&mode=all&lang=zh")
        js = f"""
        (async () => {{
            const t0 = performance.now();
            try {{
                const r = await fetch("{url}", {{credentials: "include"}});
                const d = await r.json();
                const ms = (performance.now() - t0).toFixed(0);
                return JSON.stringify({{ok: true, ms: ms, body: d.body}});
            }} catch(e) {{
                return JSON.stringify({{ok: false, err: e.message}});
            }}
        }})()
        """
        try:
            res = cdp("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True}, timeout=15)
            val = json.loads((res.get("result") or {}).get("value", "{}"))
            if not val.get("ok"):
                _log("fetch", f"[方案B] fetch 失败: {val.get('err','')}")
                break
            works = (val.get("body") or {}).get("works") or []
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
            _log("fetch", f"[方案B] 第{len(all_items)//48+1}页: {len(works)} works (累计 {len(all_items)})")
            if len(works) < 48:
                break
            offset += len(works)
            time.sleep(0.3)
        except Exception as e:
            _log("fetch", f"[方案B] 异常: {_err_type(e)} {e}")
            break
    try:
        ws.close()
    except:
        pass
    return all_items

# ══════════════════════════════════════════════════════════════
# 方案 A: CDP + Python urllib (主路径)
# ══════════════════════════════════════════════════════════════
def _fetch_via_cdp(pages):
    """主路径: CDP 读 cookie → Python urllib 直发"""
    page = next((p for p in pages if p.get("type") == "page"), None)
    if not page:
        try:
            with _LOCAL_OPENER.open(f"http://127.0.0.1:{PORT}/json/new", timeout=5) as r:
                page = json.loads(r.read())
        except:
            return None, "", ""
    
    ws_url = page["webSocketDebuggerUrl"]
    page_url = page.get("url", "")
    
    ws = create_connection(ws_url, timeout=30)
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
        try: ws.close()
        except: pass
        return None, page_url, "NO_LOGIN"
    
    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
    
    m = re.search(r".*/users/(\d+)/.*", page_url)
    uid = m.group(1) if m else None
    if not uid:
        yuid = next((c["value"] for c in cookies if c["name"] == "yuid_b"), None)
        m2 = re.search(r"\d{4,}", yuid or "")
        uid = m2.group(0) if m2 else None
    
    if not uid:
        try: ws.close()
        except: pass
        return None, page_url, "NO_UID"
    
    try: ws.close()
    except: pass
    
    all_items = []
    offset = 0
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
        "Referer": "https://www.pixiv.net/",
        "Cookie": cookie_header,
        "Accept": "application/json, text/plain, */*",
    }
    while True:
        url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
               f"?tag=&offset={offset}&limit=48&rest=show&order=desc&mode=all&lang=zh")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                d = json.loads(raw)
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
            _log("fetch", f"[方案A] 抓取失败: {_err_type(e)} {e}")
            return all_items, page_url, f"FETCH_ERR:{_err_type(e)}"
    
    return all_items, page_url, "OK"

def main():
    _log("main", f"=== 开始导入 (PORT={PORT}) ===")
    
    # ── 多来源 uid 检测 ──
    uid = ""
    settings = _load_settings()
    
    # 1. 环境变量
    uid = os.environ.get("PIXIV_UID", "")
    
    # 2. 配置文件
    if not uid:
        uid = settings.get("pixiv_uid", "")
        if uid:
            _log("main", f"从配置文件读取 uid={uid}")
    
    # 3. CDP page URL
    pages = cdp_targets()
    ws_url_for_b = None
    if pages:
        page = next((p for p in pages if p.get("type") == "page"), None)
        if page:
            page_url = page.get("url", "")
            m = re.search(r".*/users/(\d+).*", page_url)
            if m:
                uid = m.group(1)
                _log("main", f"从 CDP page URL 提取 uid={uid}")
            ws_url_for_b = page["webSocketDebuggerUrl"]
    
    # 4. 工具自带 edge_profile
    if not uid:
        uid = _detect_uid_from_edge()
        if uid:
            _log("main", f"从工具 edge_profile 检测到 uid={uid}")
    
    # 5. 用户默认 Edge profile
    if not uid:
        user_profile = _get_user_default_edge_profile()
        if user_profile:
            uid = _detect_uid_from_edge(user_profile)
            if uid:
                _log("main", f"从用户默认 Edge profile 检测到 uid={uid}")
    
    if not uid:
        _log("main", "无法自动检测 uid。请设置环境变量 PIXIV_UID=你的用户ID")
        print("请在设置中填写你的 Pixiv 用户ID，或确保 Edge 已打开收藏页")
        return 1
    
    # 记住 uid
    if not settings.get("pixiv_uid"):
        settings["pixiv_uid"] = uid
        _save_settings(settings)
    
    _log("main", f"目标 uid={uid}")
    all_items = []
    method_used = ""
    
    # ── 尝试方案 A: CDP + urllib ──
    if pages:
        _log("main", "[方案A] 尝试 CDP + Python urllib...")
        items, page_url, status = _fetch_via_cdp(pages)
        if items:
            all_items = items
            method_used = "A:CDP+urllib"
            _log("main", f"[方案A] 成功: {len(items)} works")
        elif status == "NO_LOGIN":
            _log("main", "[方案A] 无登录态, 尝试其他方案...")
        else:
            _log("main", f"[方案A] 失败: {status}, 尝试其他方案...")
    
    # ── 尝试方案 B: 浏览器内 fetch (需要 CDP) ──
    if not all_items and ws_url_for_b:
        _log("main", "[方案B] 尝试 CDP 浏览器内 fetch...")
        items = _fetch_browser_internal(ws_url_for_b, uid)
        if items:
            all_items = items
            method_used = "B:browser-fetch"
            _log("main", f"[方案B] 成功: {len(items)} works")
        else:
            _log("main", "[方案B] 失败, 尝试下一方案...")
    
    # ── 尝试方案 C: 启动新调试 Edge ──
    if not all_items:
        _log("main", "[方案C] 尝试启动新的调试 Edge 实例...")
        if _launch_edge(headless=True):
            pages = cdp_targets()
            if pages:
                items, page_url, status = _fetch_via_cdp(pages)
                if items:
                    all_items = items
                    method_used = "C:new-edge+urllib"
                    _log("main", f"[方案C] 成功: {len(items)} works")
                elif status == "NO_LOGIN":
                    _log("main", "[方案C] 新实例无登录态, 尝试有头模式...")
                    # 杀掉无头，启动有头
                    subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process -Filter \"CommandLine like '%edge_profile%'\" | Stop-Process -Force"],
                        capture_output=True, timeout=10)
                    time.sleep(2)
                    if _launch_edge(headless=False):
                        print("请在弹出的 Pixiv 页面登录后重试")
                        return 1
    
    # ── 全部失败 ──
    if not all_items:
        _log("main", "所有方案均失败")
        print("导入失败。请检查:")
        print("  1. 网络连接是否正常")
        print("  2. 已在 Edge 中登录 Pixiv")
        print("  3. 收藏是否设置为公开")
        return 1
    
    # 写入文件
    _json_data = json.dumps(all_items, ensure_ascii=False, indent=1)
    with open(DATA, "w", encoding="utf-8") as f:
        f.write(_json_data)
    
    _log("main", f"=== 完成: 导出 {len(all_items)} 幅收藏 (方案: {method_used}) ===")
    print(f"[OK] 已导出 {len(all_items)} 幅收藏到 data/bookmarks.json (方案: {method_used})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
