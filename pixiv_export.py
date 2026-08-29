#!/usr/bin/env python3
"""PixivFavSearch 收藏导出器 (CDP 方案, cookie 不落盘)

原理: 连接 Edge/Chrome 的 CDP 调试端口, 在已登录的浏览器会话内
用页面 JS fetch 抓取收藏数据, 全程不读取/保存 cookie。
"""
import os, sys, json, re, time, socket, subprocess, urllib.request, urllib.parse, base64

APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
os.makedirs(OUT, exist_ok=True)

PORT = int(os.environ.get("CDP_PORT", "9222"))
PIXIV = "https://www.pixiv.net/bookmark.php?rest=show"
try:
    from websocket import create_connection  # websocket-client
except ImportError:
    print("缺少 websocket-client, 请先: python -m pip install websocket-client")
    sys.exit(1)


def cdp_targets():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=3) as r:
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
    # 优先复用已有的 pixiv 收藏页(已登录, 带 /users/{uid}/bookmarks 路径)
    def is_bookmarks(p):
        return p.get("type") == "page" and "pixiv" in (p.get("url") or "") and "/bookmarks" in (p.get("url") or "")
    page = next((p for p in pages if is_bookmarks(p)), None)
    if not page:
        # 退而求其次: 任意 pixiv 页面
        page = next((p for p in pages if p.get("type") == "page" and "pixiv" in (p.get("url") or "")), None)
    if page:
        ws_url = page["webSocketDebuggerUrl"]
    else:
        # 新建一个干净标签页打开收藏页入口(会自动跳转到用户收藏页)
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/json/new?{urllib.parse.quote('https://www.pixiv.net/bookmark.php?rest=show')}", timeout=5
            ) as r:
                page = json.loads(r.read())
            ws_url = page["webSocketDebuggerUrl"]
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

    cmd("Page.enable")
    cmd("Runtime.enable")

    # 若当前页面不是收藏页, 导航到收藏页入口(自动跳转到 /users/{uid}/bookmarks/artworks)
    uid = None
    r = cmd("Runtime.evaluate", {"expression": "location.pathname", "returnByValue": True})
    path = (r.get("result") or {}).get("value", "")
    if "bookmarks" not in path:
        print("导航到收藏页...", flush=True)
        cmd("Page.navigate", {"url": "https://www.pixiv.net/bookmark.php?rest=show"})
        # 等跳转完成(最多 15s)
        for _ in range(15):
            time.sleep(1)
            r = cmd("Runtime.evaluate", {"expression": "location.pathname", "returnByValue": True})
            path = (r.get("result") or {}).get("value", "")
            if "/bookmarks" in path:
                break
    m = re.match(r".*/users/(\d+)/.*", path or "")
    if m:
        uid = m.group(1)
    if not uid:
        print(f"无法从页面 URL 获取用户ID (path={path!r})")
        ws.close()
        return 1

    # 检查是否登录(在收藏页上出现导航栏 = 已登录)
    r = cmd("Runtime.evaluate", {"expression": "!!document.querySelector('nav') || document.body.innerText.includes('ログイン')===false", "returnByValue": True})
    logged = (r.get("result") or {}).get("value")
    if not logged:
        print("检测到未登录, 请在刚打开的 Pixiv 页面登录(最多等 2 分钟)...", flush=True)
        waited = 0
        while waited < 120:
            time.sleep(3)
            waited += 3
            r = cmd("Runtime.evaluate", {"expression": "!!document.querySelector('nav') || document.body.innerText.includes('ログイン')===false", "returnByValue": True})
            if (r.get("result") or {}).get("value"):
                break
        else:
            print("等待登录超时。")
            ws.close()
            return 1
        time.sleep(3)

    # 页面内 fetch 抓取收藏 (浏览器会话内, cookie 不落盘)
    js = r"""
    (async () => {
      const m = location.pathname.match(/\/users\/(\d+)/);
      if (!m) return JSON.stringify({error: '无法从页面获取用户ID'});
      const uid = m[1];
      let items=[], offset=0, page=1;
      while(true){
        const url = 'https://www.pixiv.net/ajax/user/'+uid+'/illusts/bookmarks?tag=&offset='+offset+'&limit=48&rest=show&order=desc&mode=all&lang=zh';
        const r = await fetch(url, {credentials:'include'});
        if(!r.ok) break;
        const d = await r.json();
        const works = d?.body?.works || [];
        if(!works.length) break;
        items.push(...works.map(w => ({
          id: String(w.id), title: w.title,
          tags: (w.tags||[]).map(t => typeof t === 'object' ? t.tag : String(t)),
          description: w.description||'',
          url: w.url || ('https://www.pixiv.net/artworks/'+w.id),
          userId: String(w.userId), userName: w.userName,
          width: w.width, height: w.height,
          pageCount: w.pageCount, createDate: w.createDate,
          aiType: w.aiType,
        })));
        if(works.length < 48) break;
        offset += works.length; page++;
      }
      return JSON.stringify({items});
    })()
    """
    r = cmd("Runtime.evaluate", {"expression": js, "awaitPromise": True, "returnByValue": True})
    raw = r.get("result", {}).get("value")
    if not raw:
        print("抓取失败, 可能是登录态或页面结构问题。")
        ws.close()
        return 1
    data = json.loads(raw)
    items = data.get("items", [])
    if not items:
        print("未抓取到收藏。若刚登录过, 请刷新后重试。")
        ws.close()
        return 1

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    ws.close()
    print(f"[OK] 已导出 {len(items)} 幅收藏到 data/bookmarks.json")
    print("  缩略图在下次搜索时会按需下载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())