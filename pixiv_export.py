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
CONFIG_FILE = os.path.join(APP_DATA, "config.json")
os.makedirs(OUT, exist_ok=True)

def get_proxy():
    """从 config.json 读取代理地址, 默认 http://127.0.0.1:10808"""
    if os.path.exists(CONFIG_FILE):
        try:
            config = json.load(open(CONFIG_FILE, "r", encoding="utf-8"))
            return config.get("proxy", "http://127.0.0.1:10808")
        except: pass
    return "http://127.0.0.1:10808"

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

def _edge_exe_path():
    """找 msedge.exe: 常见安装位置 + PATH。"""
    import shutil
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return shutil.which("msedge")

def _edge_debug_running(port=9222):
    """CDP 端口是否已有 Edge 在监听。"""
    try:
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        conn.request("GET", "/json/version")
        conn.getresponse().read()
        conn.close()
        return True
    except Exception:
        return False

def launch_edge_for_login(port=9222):
    """用调试端口启动独立 Edge 实例打开 pixiv 登录页(不动用户正在用的 Edge)。
    新测试机上 Edge 默认不开调试端口 → 方式A 之前 100% 失败。
    独立 user-data-dir 避免和用户日常 Edge 冲突(配置文件锁)。
    Returns: (ok, msg)"""
    if _edge_debug_running(port):
        return True, "CDP 已在运行"
    exe = _edge_exe_path()
    if not exe:
        return False, "未找到 Microsoft Edge"
    import tempfile, subprocess
    profile = os.path.join(tempfile.gettempdir(), "pfs_edge_login")
    try:
        subprocess.Popen([
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check",
            "https://www.pixiv.net/login.php",
        ], close_fds=True)
        # 等端口就绪(最多 10s)
        import time as _t
        for _ in range(20):
            _t.sleep(0.5)
            if _edge_debug_running(port):
                return True, "Edge 已启动(独立实例)"
        return False, "Edge 启动超时"
    except Exception as e:
        return False, repr(e)[:80]

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
        ws_opts = {"timeout": 10, "suppress_origin": True}  # Edge 153+ 拒绝带 Origin 的握手(403)
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

# 进度回调: 由 server 层注入({"total":N,"done":M}), 供前端显示实时进度
_PROGRESS_CB = None

def set_progress_callback(cb):
    """注入进度字典(可变对象, 由本模块回写)。传 None 关闭。"""
    global _PROGRESS_CB
    _PROGRESS_CB = cb

def _fetch_total_bookmarks(uid, cookie_header, proxy_url):
    """取用户收藏总数(公开/私密合计), 作为进度百分比的分母。
    Pixiv 的 bookmarks API 不返回总数, 改从用户主页 HTML 里抽。取不到返回 0。"""
    try:
        import urllib.request as _ur, re as _re, gzip as _gz, io as _io
        _opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": proxy_url, "https": proxy_url})) if proxy_url else urllib.request.build_opener()
        req = _ur.Request(f"https://www.pixiv.net/users/{uid}",
                          headers={"Cookie": cookie_header,
                                   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                   "Accept-Encoding": "gzip"})
        with _opener.open(req, timeout=20) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = _gz.decompress(raw)
            html = raw.decode("utf-8", "ignore")
        # 形如 "bookmarks":{"total":8465} 或 收藏数文本
        m = _re.search(r'"bookmarkCount"\s*:\s*(\d+)', html) or \
            _re.search(r'bookmarks[^{]*\{[^}]*"total"\s*:\s*(\d+)', html)
        if m:
            n = int(m.group(1))
            _log("main", f"[progress] 收藏总数={n}")
            return n
    except Exception as e:
        _log("main", f"[progress] 取总数失败(不影响导入): {e}")
    return 0

def main():
    """导入入口: 临时把 DNS 改成"域名交代理远端解析", 结束后必定恢复。

    覆盖是【进程级】的, 而 main() 在桌面版里由后台线程调用。之前覆盖后
    从不恢复 → 进程内所有后续 DNS 解析都被改成直通, 服务端下载缩略图时
    连代理都走不通(解析出真实 IP 直连 → 超时), 实测造成整批图片变占位图。
    """
    _log("main", "=== Import Start ===")
    _orig_gai = socket.getaddrinfo

    def _remote_gai(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    socket.getaddrinfo = _remote_gai
    try:
        return _main_impl()
    finally:
        socket.getaddrinfo = _orig_gai
        _log("main", "=== Import End (DNS restored) ===")


def _main_impl():
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
    
    # 2.5 增量导入: 读取已有数据, 建立 bookmarkId 集合 / 最新 bookmarkId / 作品id 索引
    old_list = []
    old_by_id = {}
    old_bids = set()
    max_old_bid = 0
    if os.path.exists(DATA):
        try:
            old_list = json.load(open(DATA, "r", encoding="utf-8")) or []
            if not isinstance(old_list, list):
                old_list = []
            for it in old_list:
                wid = it.get("id")
                if wid is not None:
                    old_by_id[str(wid)] = it
                try:
                    bid = int(it.get("bookmarkId"))
                except (TypeError, ValueError):
                    continue
                old_bids.add(bid)
                if bid > max_old_bid:
                    max_old_bid = bid
        except Exception as e:
            _log("main", f"读取已有数据失败(按空库处理): {e}")
            old_list, old_by_id, old_bids, max_old_bid = [], {}, set(), 0
    _log("main", f"增量导入: 已有 {len(old_list)} 条, 最新 bookmarkId={max_old_bid}")

    _log("main", f"Fetching bookmarks for uid {uid}...")
    # 新增条目(结构与原代码完全一致); 旧条目合并时直接从 old_list 原样取
    new_items = []
    # bookmarkId -> [自建收藏标签] 映射, 从每页响应的 bookmarkTags 字段顺路收集
    # (pixiv 官方 API: body.bookmarkTags = {"<bookmarkData.id>": ["标签A", "标签B"]})
    collected_tags = {}
    fetched_count = 0    # 本次已抓取(新增)条数
    page_no = 0          # 全局页码(show/hide 连续计数)
    reached_old = False  # 命中旧收藏 -> 停止全部抓取
    
    proxy_url = get_proxy()
    proxy = urllib.request.ProxyHandler({
        'http': proxy_url,
        'https': proxy_url
    })
    opener = urllib.request.build_opener(proxy)
    
    for rest in ("show", "hide"):
        if reached_old:
            break
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
                body = d.get("body") or {}
                works = body.get("works") or []
                # 顺路收集收藏标签映射 (bookmarkData.id -> tags)
                btags = body.get("bookmarkTags") or {}
                if isinstance(btags, dict):
                    collected_tags.update(btags)
                if not works:
                    break
                page_no += 1
                page_new = 0
                for w in works:
                    bm = w.get("bookmarkData") or {}
                    bid_raw = bm.get("id")
                    try:
                        bid = int(bid_raw)
                    except (TypeError, ValueError):
                        bid = None
                    # order=desc: 命中 <= max_old_bid 说明后面全是旧收藏, 立即停止全部抓取
                    if bid is not None and max_old_bid and bid <= max_old_bid:
                        reached_old = True
                        break
                    new_items.append({
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
                        "xRestrict": w.get("xRestrict", 0),
                        "bookmarkId": str(bm.get("id", "")) if bm.get("id") else "",
                    })
                    page_new += 1
                    fetched_count += 1
                # 进度上报: done=本次已抓取条数, total=已抓取+已有旧条目
                if _PROGRESS_CB:
                    _PROGRESS_CB["done"] = fetched_count
                    _PROGRESS_CB["total"] = max(fetched_count + len(old_list), fetched_count)
                    _PROGRESS_CB["cur"] = f"第 {page_no} 页 · 新增 {fetched_count} 条"
                _log("main", f"第 {page_no} 页: 新增 {page_new} 条")
                if reached_old:
                    break
                if len(works) < 48:
                    break
                offset += len(works)
                time.sleep(0.3)
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    _log("main", f"[{rest}] 403 (private)")
                    break
                elif e.code == 409:
                    _log("main", f"[{rest}] 409 conflict, retrying in 2s...")
                    time.sleep(2)
                    continue
                elif e.code == 429:
                    _log("main", f"[{rest}] 429 rate-limited, cooling 30s...")
                    time.sleep(30)
                    continue
                else:
                    _log("main", f"[{rest}] HTTP {e.code}")
                    break
            except urllib.error.URLError as e:
                # SSL 错误处理（如 EOF occurred）
                err_str = str(e)
                if "UNEXPECTED_EOF_WHILE_READING" in err_str or "EOF occurred" in err_str:
                    _log("main", f"[{rest}] SSL EOF error, retrying in 3s... ({err_str[:50]})")
                    time.sleep(3)
                    continue
                _log("main", f"[{rest}] URLError: {e}")
                break
            except ConnectionError as e:
                # pixiv 中途掐线(WinError 10054): 退避重试, 已抓数据不丢
                _log("main", f"[{rest}] connection reset, retry in 10s (offset={offset})...")
                time.sleep(10)
                continue
            except Exception as e:
                err_str = str(e)
                if "10054" in err_str or "forcibly closed" in err_str or "远程主机强迫关闭" in err_str:
                    _log("main", f"[{rest}] connection reset, retry in 10s (offset={offset})...")
                    time.sleep(10)
                    continue
                _log("main", f"[{rest}] Error: {e}")
                break
    
    # 5. 合并: 新收藏在前(按收藏时间倒序), 旧收藏原顺序不变
    new_bids = set()
    for it in new_items:
        try:
            new_bids.add(int(it.get("bookmarkId")))
        except (TypeError, ValueError):
            pass
    merged_old = []
    for it in old_list:
        try:
            obid = int(it.get("bookmarkId"))
        except (TypeError, ValueError):
            obid = None
        if obid is not None and obid in new_bids:
            continue
        # 旧条目直接复用 old_by_id 里的原对象(按原顺序)
        merged_old.append(old_by_id.get(str(it.get("id")), it))
    final = new_items + merged_old

    if not new_items:
        _log("main", "无新增收藏")

    # 写盘保护: final 为空则报错返回, 绝不清空旧库
    if len(final) <= 0:
        _log("main", "ERROR: final 为空, 不写盘")
        print("ERROR: No items fetched")
        return 1

    # 原子写入: 先写临时文件再替换, 避免半成品数据砸掉旧库
    _tmp = DATA + ".tmp"
    json.dump(final, open(_tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(_tmp, DATA)

    # 收尾: 进度打满 100%
    if _PROGRESS_CB:
        _PROGRESS_CB["done"] = len(final)
        _PROGRESS_CB["total"] = len(final)
        _PROGRESS_CB["new_count"] = len(new_items)
        _PROGRESS_CB["cur"] = f"完成: 新增 {len(new_items)} 条"

    _log("main", f"=== 增量完成: 新增 {len(new_items)} 条, 共 {len(final)} 条 ===")
    print(f"OK: {len(final)} bookmarks imported (+{len(new_items)} new)")
    
    # 抓取收藏标签
    try:
        _save_coltags_from_collected(final, collected_tags)
    except Exception as e:
        _log("main", f"保存收藏标签失败: {e}")
    
    return 0

def _save_coltags_from_collected(all_items, collected_tags):
    """从主下载循环顺路收集的 bookmarkTags 映射生成 coltags.json。

    旧方案(ajax/user/{uid}/illusts/bookmarks/tags)已 404 —— pixiv 已下线该端点。
    新方案零额外请求: 每页 body.bookmarkTags = {"<bookmarkId>": ["标签", ...]},
    作品的 bookmarkData.id 就是 key。空结果保护: 有作品但映射为空时不覆盖旧文件。
    """
    COLTAGS = os.path.join(OUT, "coltags.json")
    if not collected_tags:
        if all_items:
            _log("main", "bookmarkTags 映射为空(账号可能没打收藏标签), 保留旧 coltags.json")
            return
        return
    
    # 反查: bookmarkId -> 作品 id
    bid2wid = {it.get("bookmarkId", ""): it.get("id", "") for it in all_items if it.get("bookmarkId")}
    
    result = {}
    n_mapped = 0
    for bid, tags in collected_tags.items():
        wid = bid2wid.get(str(bid), "")
        if not wid:
            continue
        for t in tags or []:
            if t:
                result.setdefault(t, []).append(wid)
                n_mapped += 1

    # 增量导入时 collected_tags 只覆盖本次抓到的页, 直接覆盖会把旧标签全丢掉。
    # 所以先读旧文件, 保留仍然存在的作品映射, 再把本次结果合并进去。
    merged = {}
    cur_ids = {str(it.get("id")) for it in all_items if it.get("id")}
    try:
        if os.path.exists(COLTAGS):
            old_raw = json.load(open(COLTAGS, encoding="utf-8")) or {}
            if isinstance(old_raw, dict):
                for t, ids in old_raw.items():
                    keep = [i for i in (ids or []) if str(i) in cur_ids]
                    if keep:
                        merged[t] = list(dict.fromkeys(keep))
    except Exception as e:
        _log("main", f"读取旧 coltags.json 失败(按空处理): {e}")
    for t, ids in result.items():
        seen = merged.setdefault(t, [])
        for i in ids:
            if i not in seen:
                seen.append(i)

    if not merged:
        _log("main", "收藏标签映射后为空, 保留旧 coltags.json")
        return

    json.dump(merged, open(COLTAGS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    _log("main", f"收藏标签已保存: {COLTAGS} ({len(merged)} 个标签, {sum(len(v) for v in merged.values())} 条映射)")

if __name__ == "__main__":
    sys.exit(main())
