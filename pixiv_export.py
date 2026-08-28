#!/usr/bin/env python3
"""PixivFavSearch 收藏导出器 (CDP 方案, cookie 不落盘)

原理: 连接 Edge/Chrome 的 CDP 调试端口, 在已登录的浏览器会话内
用页面 JS fetch 抓取收藏数据, 全程不读取/保存 cookie。
"""
import os, sys, json, time, socket, urllib.request, base64

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
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
        print("请用调试模式打开 Edge: 开始菜单搜索'Edge' → 或用命令:")
        print(f'  msedge.exe --remote-debugging-port={PORT}')
        return None


def main():
    pages = cdp_targets()
    if not pages:
        return 1
    page = next((p for p in pages if p.get("type") == "page"), pages[0])
    ws_url = page["webSocketDebuggerUrl"]
    ws = create_connection(ws_url, timeout=30)
    _id = 0

    def cmd(method, params=None):
        global _id
        _id += 1
        ws.send(json.dumps({"id": _id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == _id:
                return msg.get("result", {})

    # 导航到收藏页
    cmd("Page.enable")
    cmd("Runtime.enable")
    cmd("Page.navigate", {"url": PIXIV})
    time.sleep(6)  # 等加载

    # 检查是否登录
    r = cmd("Runtime.evaluate", {"expression": '!!document.querySelector("body")', "returnByValue": True})
    # 判断登录态
    expr_logged = '!!document.querySelector("nav")||document.body.innerText.includes("ログイン")===false'
    r = cmd("Runtime.evaluate", {"expression": "document.title", "returnByValue": True})
    title = r.get("result", {}).get("value", "")
    if "login" in title.lower() or "登录" in title:
        print("检测到未登录。请在刚打开的 Pixiv 页面登录, 登录后按回车继续...")
        input()
        time.sleep(3)

    # 页面内 fetch 抓取收藏 (浏览器会话内, cookie 不落盘)
    js = r"""
    (async () => {
      const cn = () => document.cookie.split(';').length; // 触发确认在浏览器上下文
      let items=[], offset=0, page=1;
      while(true){
        const url = 'https://www.pixiv.net/ajax/user/_/bookmarks?rest=show&offset='+offset+'&limit=48&lang=zh';
        const r = await fetch(url, {credentials:'include'});
        if(!r.ok) break;
        const d = await r.json();
        const works = d?.body?.works || [];
        items.push(...works.map(w => ({
          id: String(w.id), title: w.title,
          tags: (w.tags||[]).map(t=>t.tag),
          description: w.description||'',
          url: 'https://www.pixiv.net/artworks/'+w.id,
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
    print(f"✓ 已导出 {len(items)} 幅收藏到 data/bookmarks.json")
    print("  缩略图在下次搜索时会按需下载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())