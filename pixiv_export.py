#!/usr/bin/env python3
"""PixivFavSearch 收藏导出器 (CDP 读 cookie + Python 直发, cookie 不落盘)

原理:
1. 连接 Edge/Chrome 的 CDP 调试端口, 用 Network.getCookies 读取页面 cookie
   (含 HttpOnly 的 PHPSESSID 登录态), 全程不把 cookie 写入磁盘。
2. 用 Python urllib.request 直接请求 pixiv ajax API 抓取收藏——
   完全绕过页面 Service Worker 对 fetch 的拦截(页面内 JS fetch 会被 SW
   拦截后挂起, 永不 resolve)。
"""
import os, sys, json, re, time, socket, subprocess, urllib.request, urllib.parse, base64

APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
os.makedirs(OUT, exist_ok=True)

PORT = int(os.environ.get("CDP_PORT", "9222"))
PIXIV = "https://www.pixiv.net/bookmark.php?rest=show"

# 调试日志开关: 环境变量 PIXIV_DEBUG=1 启用详细日志
_DEBUG = os.environ.get("PIXIV_DEBUG", "0") == "1"

def _log(tag, msg):
    """带标签的调试日志, 格式: [tag] msg"""
    print(f"[{tag}] {msg}", flush=True)

# 本地 CDP 请求必须直连, 绝不能走系统/环境代理
# (否则 urllib 会把 http://127.0.0.1:9222 通过 SOCKS5/HTTP 代理转发,
# 代理没开或拒绝时本地调试端口永远连不上 → 导入失败)
_NO_PROXY = urllib.request.ProxyHandler({})
_LOCAL_OPENER = urllib.request.build_opener(_NO_PROXY)

try:
    from websocket import create_connection  # websocket-client
except ImportError:
    print("缺少 websocket-client, 请先: python -m pip install websocket-client")
    sys.exit(1)


def cdp_targets():
    try:
        _t0 = time.time()
        with _LOCAL_OPENER.open(f"http://127.0.0.1:{PORT}/json", timeout=3) as r:
            data = json.loads(r.read())
        _ms = (time.time() - _t0) * 1000
        if _DEBUG:
            _pages = [p for p in data if p.get("type") == "page"]
            _log("cdp", f"连接成功({_ms:.0f}ms), {len(data)} targets, {len(_pages)} pages")
            for p in _pages[:3]:
                _log("cdp", f"  page: {p.get('url','')[:80]}")
        return data
    except Exception as e:
        _ms = (time.time() - _t0) * 1000 if '_t0' in dir() else 0
        _log("cdp", f"连接失败({_ms:.0f}ms): {e}")
        return None


_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_EDGE_PROFILE = os.path.join(APP_DATA, "edge_profile")  # 独立配置, 不干扰日常浏览器


def _launch_edge(headless=True):
    """拉起调试版 Edge。headless=True 时不弹窗(后台跑 CDP);
    headless=False 时显示窗口(供首次登录 Pixiv 用)。"""
    edge = next((p for p in _EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        _log("edge", "未找到 Edge 浏览器")
        return False
    os.makedirs(_EDGE_PROFILE, exist_ok=True)
    mode = "无头" if headless else "有头(登录用)"
    _log("edge", f"启动 [{mode}] profile={_EDGE_PROFILE}")
    args = [
        edge,
        f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={_EDGE_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if headless:
        args[3:3] = ["--headless=new", "--disable-gpu"]
    args.append(PIXIV)
    _log("edge", f"cmdline: {' '.join(args[:4])} ...")
    p = subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _log("edge", f"PID={p.pid}, 等待CDP就绪(≤20s)...")
    for i in range(20):
        time.sleep(1)
        if cdp_targets():
            _log("edge", f"CDP 就绪 ({i+1}s)")
            return True
    _log("edge", "启动超时 (20s)")
    return False


def ensure_cdp_browser():
    """确保有调试浏览器可用。已连上返回 True; 否则自动拉起一个带调试端口的 Edge。"""
    if cdp_targets():
        _log("edge", "复用已有调试实例")
        return True
    _log("edge", "无可用调试实例, 自动拉起")
    if _launch_edge(headless=True):
        return True
    _log("edge", "自动拉起失败")
    return False


def main():
    _log("main", f"=== 开始导入 (PORT={PORT}, DEBUG={'ON' if _DEBUG else 'OFF'}) ===")
    _t_start = time.time()

    # 阶段1: 确保 CDP 可用
    _log("main", "[阶段1] 确保 CDP 浏览器就绪")
    pages = ensure_cdp_browser() and cdp_targets()
    if not pages:
        _log("main", "CDP 不可用, 退出")
        return 1
    _log("main", f"CDP 就绪, {len(pages)} targets")

    # 阶段2: 选择 page target
    page = next((p for p in pages if p.get("type") == "page"), None)
    if page:
        ws_url = page["webSocketDebuggerUrl"]
        page_url = page.get("url") or ""
        _log("main", f"[阶段2] 复用已有 page: {page_url[:80]}")
    else:
        _log("main", f"[阶段2] 无 page target, 新建标签页")
        try:
            with _LOCAL_OPENER.open(
                f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote(PIXIV)}", timeout=5
            ) as r:
                page = json.loads(r.read())
            ws_url = page["webSocketDebuggerUrl"]
            page_url = page.get("url") or ""
            _log("main", f"新建标签页: {page_url[:80]}")
        except Exception as e:
            _log("main", f"新建标签页失败: {e}")
            return 1

    # 阶段3: 连接 WebSocket
    _log("main", f"[阶段3] 连接 WebSocket: {ws_url[:60]}...")
    try:
        ws = create_connection(ws_url, timeout=30)
        _log("main", "WebSocket 连接成功")
    except Exception as e:
        _log("main", f"WebSocket 连接失败: {e}")
        return 1

    _id = 0

    def cmd(method, params=None, timeout=60):
        nonlocal _id
        _id += 1
        _cid = _id
        _t0 = time.time()
        if _DEBUG:
            _log("cmd", f"#{_cid} {method} (timeout={timeout}s) params={json.dumps(params, ensure_ascii=False)[:100]}")
        ws.send(json.dumps({"id": _cid, "method": method, "params": params or {}}))
        ws.settimeout(timeout)
        try:
            while True:
                msg = json.loads(ws.recv())
                if _DEBUG and msg.get("id") != _cid:
                    _log("cmd", f"  收到事件: {msg.get('method','?')}")
                if msg.get("id") == _cid:
                    _ms = (time.time() - _t0) * 1000
                    _res = msg.get("result", {})
                    if _DEBUG:
                        _log("cmd", f"#{_cid} 响应({_ms:.0f}ms) keys={list(_res.keys())}")
                    return _res
        except Exception as e:
            _ms = (time.time() - _t0) * 1000
            _log("cmd", f"#{_cid} 超时/断开({_ms:.0f}ms): {e}")
            return {}

    def reconnect():
        """断开并重连 WebSocket(登录等待/导航时用)。"""
        nonlocal ws, _id
        _log("ws", "重连 WebSocket")
        try:
            ws.close()
        except Exception:
            pass
        ws = create_connection(ws_url, timeout=30)
        _id = 0
        _log("ws", "重连完成")

    def get_cookies():
        """读页面全部 cookie(含 HttpOnly 的 PHPSESSID)。"""
        reconnect()
        cmd("Network.enable")
        r = cmd("Network.getCookies", {"urls": ["https://www.pixiv.net"]})
        cookies = r.get("cookies", [])
        _log("cookie", f"获取 {len(cookies)} 个 cookie")
        return cookies

    # 阶段4: 健康检查
    _log("main", "[阶段4] CDP 健康检查 (5s)")
    _test_start = time.time()
    try:
        _test_r = cmd("Network.getCookies", {"urls": ["https://www.pixiv.net"]}, timeout=5)
        _test_ck = _test_r.get("cookies", [])
        _log("main", f"健康检查通过: {len(_test_ck)} cookie ({(time.time()-_test_start)*1000:.0f}ms)")
    except Exception as e:
        _log("main", f"健康检查失败({(time.time()-_test_start)*1000:.0f}ms): {e}, 尝试重连")
        reconnect()
        cmd("Network.enable")

    # 阶段5: 获取 cookie + 登录态
    _log("main", "[阶段5] 获取登录态")
    cookies = get_cookies()
    phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
    if phpsessid:
        _log("main", f"已登录 (PHPSESSID={phpsessid[:8]}...)")
    else:
        _log("main", "未登录")
        print("未检测到登录态，无头模式下无法看到登录页，切换可见模式...", flush=True)
        try:
            ws.close()
        except Exception:
            pass
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"CommandLine like '%edge_profile%'\" | Stop-Process -Force"],
            capture_output=True, timeout=10)
        _log("edge", "杀掉无头实例, 等待2s")
        time.sleep(2)
        if not _launch_edge(headless=False):
            _log("edge", "有头模式启动失败")
            return 1
        pages = cdp_targets()
        if not pages:
            _log("edge", "有头模式 CDP 不可用")
            return 1
        page = next((p for p in pages if p.get("type") == "page"), None)
        if page:
            ws_url = page["webSocketDebuggerUrl"]
        else:
            try:
                with _LOCAL_OPENER.open(
                    f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote(PIXIV)}", timeout=5
                ) as r:
                    page = json.loads(r.read())
                ws_url = page["webSocketDebuggerUrl"]
            except Exception as e:
                _log("main", f"新建标签页失败: {e}")
                return 1
        reconnect()
        cookies = get_cookies()
        phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
        print("请在弹出的 Pixiv 页面登录后重试", flush=True)
        _log("main", "等待用户登录 (≤120s)...")
        waited = 0
        while waited < 120:
            time.sleep(3)
            waited += 3
            cookies = get_cookies()
            phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
            if phpsessid:
                _log("main", f"登录成功 (等待{waited}s)")
                break
        else:
            _log("main", "登录超时")
            try:
                ws.close()
            except Exception:
                pass
            return 1
        time.sleep(3)

    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    # 阶段6: 获取用户ID
    _log("main", "[阶段6] 提取用户ID")
    m = re.search(r".*/users/(\d+)/.*", page_url)
    uid = m.group(1) if m else None
    if uid:
        _log("main", f"从 page URL 提取 uid={uid}")
    else:
        yuid = next((c["value"] for c in cookies if c["name"] == "yuid_b"), None)
        m = re.search(r"\d{4,}", yuid or "")
        if m:
            uid = m.group(0)
            _log("main", f"从 yuid_b 提取 uid={uid}")
    if not uid:
        _log("main", "导航到收藏页获取 uid")
        reconnect()
        cmd("Page.navigate", {"url": "https://www.pixiv.net/bookmark.php?rest=show"})
        path = ""
        for i in range(15):
            time.sleep(1)
            r = cmd("Runtime.evaluate", {"expression": "location.pathname", "returnByValue": True})
            path = (r.get("result") or {}).get("value", "")
            if _DEBUG:
                _log("nav", f"  pathname[{i+1}]: {path}")
            if "/bookmarks" in path:
                break
        m = re.search(r".*/users/(\d+)/.*", path or "")
        if m:
            uid = m.group(1)
            _log("main", f"从导航 pathname 提取 uid={uid}")
    try:
        ws.close()
    except Exception:
        pass
    if not uid:
        _log("main", "无法获取 uid")
        return 1
    _log("main", f"最终 uid={uid}")

    # 阶段7: 抓取收藏
    _log("main", "[阶段7] 抓取收藏")
    all_items = []
    offset = 0
    _proxies = urllib.request.getproxies()
    if _proxies:
        _log("proxy", f"环境代理: {_proxies}")

    # 诊断: 用 CDP 在浏览器内发 fetch, 对比 Python urllib
    # (浏览器能加载 pixiv 页面, 但 Python 走代理可能超时; 用来区分是代理问题还是 Python 特有问题)
    _diag_url = f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks?tag=&offset=0&limit=4&rest=show&order=desc&mode=all&lang=zh"
    _log("diag", f"浏览器内 fetch 测试: {_diag_url[:80]}...")
    try:
        _diag_js = f"""
        (async () => {{
            const t0 = performance.now();
            try {{
                const r = await fetch("{_diag_url}", {{credentials: "include"}});
                const d = await r.json();
                const ms = (performance.now() - t0).toFixed(0);
                return JSON.stringify({{ok: true, ms: ms, works: (d.body?.works || []).length, status: r.status}});
            }} catch(e) {{
                const ms = (performance.now() - t0).toFixed(0);
                return JSON.stringify({{ok: false, ms: ms, err: e.message}});
            }}
        }})()
        """
        _diag_r = cmd("Runtime.evaluate", {"expression": _diag_js, "awaitPromise": True, "returnByValue": True}, timeout=15)
        _diag_res = json.loads((_diag_r.get("result") or {}).get("value", "{}"))
        if _diag_res.get("ok"):
            _log("diag", f"浏览器内 fetch 成功: {_diag_res.get('ms')}ms, {_diag_res.get('works')} works")
        else:
            _log("diag", f"浏览器内 fetch 失败: {_diag_res.get('ms')}ms, err={_diag_res.get('err','')}")
    except Exception as e:
        _log("diag", f"浏览器内 fetch 测试异常: {e}")

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"),
        "Referer": "https://www.pixiv.net/",
        "Cookie": cookie_header,
        "Accept": "application/json, text/plain, */*",
    }
    _page_num = 0
    while True:
        _page_num += 1
        url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
               f"?tag=&offset={offset}&limit=48&rest=show&order=desc&mode=all&lang=zh")
        works = None
        for attempt in range(3):
            _t0 = time.time()
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    _ms = (time.time() - _t0) * 1000
                    _raw = resp.read()
                    d = json.loads(_raw)
                works = (d.get("body") or {}).get("works") or []
                _log("fetch", f"第{_page_num}页(尝试{attempt+1}) {_ms:.0f}ms, {len(works)} works, {len(_raw)} bytes")
                break
            except Exception as e:
                _ms = (time.time() - _t0) * 1000
                if attempt < 2:
                    _log("fetch", f"第{_page_num}页(尝试{attempt+1}) 失败({_ms:.0f}ms): {e}, 2s后重试")
                    time.sleep(2)
                else:
                    _log("fetch", f"第{_page_num}页(尝试{attempt+1}) 最终失败({_ms:.0f}ms): {e}")
        if not works:
            if _page_num == 1:
                _log("main", "第1页即无数据, 退出")
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
        offset += len(works)
        _log("fetch", f"累计 {len(all_items)} works")
        if len(works) < 48:
            _log("fetch", f"末页({len(works)}<48), 结束")
            break
        time.sleep(0.3)

    if not all_items:
        _log("main", "未抓取到任何收藏")
        print("未抓取到收藏。请确认已登录后重试。")
        return 1

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=1)
    _log("main", f"=== 完成: 导出 {len(all_items)} 幅收藏到 {DATA} (耗时 {time.time()-_t_start:.1f}s) ===")
    print(f"[OK] 已导出 {len(all_items)} 幅收藏到 data/bookmarks.json")
    print("  缩略图在下次搜索时会按需下载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
