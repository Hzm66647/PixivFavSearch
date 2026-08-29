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
        with _LOCAL_OPENER.open(f"http://127.0.0.1:{PORT}/json", timeout=3) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"连接 CDP 端口 {PORT} 失败: {e}")
        return None


_EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_EDGE_PROFILE = os.path.join(APP_DATA, "edge_profile")  # 独立配置, 不干扰日常浏览器


def ensure_cdp_browser():
    """确保有调试浏览器可用。已连上返回 True; 否则自动拉起一个带调试端口的 Edge。"""
    if cdp_targets():
        return True
    edge = next((p for p in _EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        print("未找到 Edge 浏览器, 无法自动启动调试实例。")
        return False
    os.makedirs(_EDGE_PROFILE, exist_ok=True)
    print(f"自动启动调试版 Edge (profile: {_EDGE_PROFILE}) ...", flush=True)
    subprocess.Popen([
        edge,
        f"--remote-debugging-port={PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={_EDGE_PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        PIXIV,  # 直接打开收藏页
    ], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    # 等待 CDP 就绪(最多 20s)
    for _ in range(20):
        time.sleep(1)
        if cdp_targets():
            return True
    print("调试 Edge 启动超时。")
    return False


def main():
    pages = ensure_cdp_browser() and cdp_targets()
    if not pages:
        return 1
    # 任意 type=page 的 target 即可 —— 只需要它的 CDP 会话读 cookie, 不需要书签页
    page = next((p for p in pages if p.get("type") == "page"), None)
    if page:
        ws_url = page["webSocketDebuggerUrl"]
        page_url = page.get("url") or ""
    else:
        # 新建一个干净标签页打开收藏页入口
        try:
            with _LOCAL_OPENER.open(
                f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote(PIXIV)}", timeout=5
            ) as r:
                page = json.loads(r.read())
            ws_url = page["webSocketDebuggerUrl"]
            page_url = page.get("url") or ""
        except Exception as e:
            print(f"新建标签页失败: {e}")
            return 1

    ws = create_connection(ws_url, timeout=30)
    _id = 0

    def cmd(method, params=None, timeout=60):
        nonlocal _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        ws.settimeout(timeout)
        try:
            while True:
                msg = json.loads(ws.recv())
                # 跳过事件消息(没有 id), 只收响应
                if msg.get("id") == _id:
                    return msg.get("result", {})
        except Exception as e:
            print(f"CDP 命令超时/断开: {method} - {e}")
            return {}

    def reconnect():
        """断开并重连 WebSocket(登录等待/导航时用)。"""
        nonlocal ws, _id
        try:
            ws.close()
        except Exception:
            pass
        ws = create_connection(ws_url, timeout=30)
        _id = 0

    def get_cookies():
        """读页面全部 cookie(含 HttpOnly 的 PHPSESSID)。"""
        reconnect()
        cmd("Network.enable")
        r = cmd("Network.getCookies", {"urls": ["https://www.pixiv.net"]})
        return r.get("cookies", [])

    # 快速健康检查: 5 秒内看 CDP 是否正常响应
    print("检查 CDP 连接...", flush=True)
    _test_start = time.time()
    try:
        _test_r = cmd("Network.getCookies", {"urls": ["https://www.pixiv.net"]}, timeout=5)
        _test_ck = _test_r.get("cookies", [])
        print(f"CDP 响应正常, 已获取 {len(_test_ck)} 个 cookie(耗时 {time.time()-_test_start:.1f}s)", flush=True)
    except Exception as e:
        print(f"CDP 健康检查失败: {e}, 尝试重新连接...", flush=True)
        reconnect()
        cmd("Network.enable")

    cookies = get_cookies()
    phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
    if not phpsessid:
        print("未检测到登录态，请在弹出的 Pixiv 页面登录后重试", flush=True)
        waited = 0
        while waited < 120:
            time.sleep(3)
            waited += 3
            cookies = get_cookies()
            phpsessid = next((c["value"] for c in cookies if c["name"] == "PHPSESSID"), None)
            if phpsessid:
                break
        else:
            print("等待登录超时。")
            try:
                ws.close()
            except Exception:
                pass
            return 1
        time.sleep(3)

    cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    # 获取用户ID: 优先从页面 URL 提取
    m = re.search(r".*/users/(\d+)/.*", page_url)
    uid = m.group(1) if m else None
    if not uid:
        # 兜底1: cookie 里的 yuid_b 带用户ID
        yuid = next((c["value"] for c in cookies if c["name"] == "yuid_b"), None)
        m = re.search(r"\d{4,}", yuid or "")
        if m:
            uid = m.group(0)
    if not uid:
        # 兜底2: 导航标签页到收藏页入口(会自动跳转到 /users/{uid}/bookmarks), 取 pathname
        print("导航到收藏页获取用户ID...", flush=True)
        reconnect()
        cmd("Page.navigate", {"url": "https://www.pixiv.net/bookmark.php?rest=show"})
        path = ""
        for _ in range(15):
            time.sleep(1)
            r = cmd("Runtime.evaluate", {"expression": "location.pathname", "returnByValue": True})
            path = (r.get("result") or {}).get("value", "")
            if "/bookmarks" in path:
                break
        m = re.search(r".*/users/(\d+)/.*", path or "")
        if m:
            uid = m.group(1)
    try:
        ws.close()
    except Exception:
        pass
    if not uid:
        print("无法从页面获取用户ID。")
        return 1

    # 直发请求抓取收藏 (Python urllib, 完全绕过页面 Service Worker 拦截)
    print("开始抓取收藏...", flush=True)
    all_items = []
    offset = 0
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"),
        "Referer": "https://www.pixiv.net/",
        "Cookie": cookie_header,
        "Accept": "application/json, text/plain, */*",
    }
    while True:
        url = (f"https://www.pixiv.net/ajax/user/{uid}/illusts/bookmarks"
               f"?tag=&offset={offset}&limit=48&rest=show&order=desc&mode=all&lang=zh")
        works = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    d = json.loads(resp.read())
                works = (d.get("body") or {}).get("works") or []
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    print(f"第 {offset // 48 + 1} 页抓取失败: {e}")
        if not works:
            break
        for w in works:
            all_items.append({
                "id": str(w.get("id")),
                "title": w.get("title", ""),
                "tags": [t.get("tag", "") if isinstance(t, dict) else str(t)
                         for t in (w.get("tags") or [])],
                "description": w.get("description", ""),
                "url": w.get("url", ""),   # ⚠️ 缩略图URL (i.pximg.net), 不是作品页URL
                "userId": str(w.get("userId", "")),
                "userName": w.get("userName", ""),
                "width": w.get("width"),
                "height": w.get("height"),
                "pageCount": w.get("pageCount"),
                "createDate": w.get("createDate", ""),
                "aiType": w.get("aiType"),
            })
        offset += len(works)
        if len(works) < 48:
            break
        time.sleep(0.3)  # 避免请求过快

    if not all_items:
        print("未抓取到收藏。请确认已登录后重试。")
        return 1

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=1)
    print(f"[OK] 已导出 {len(all_items)} 幅收藏到 data/bookmarks.json")
    print("  缩略图在下次搜索时会按需下载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
