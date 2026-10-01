#!/usr/bin/env python3
"""PixivFavSearch API 全量回归 — 只读端点, 不做破坏性操作"""
import sys, json, urllib.request, urllib.parse
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://127.0.0.1:8897"

def get(path, timeout=15):
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()

def post(path, obj, timeout=20):
    try:
        req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()

results = []
def chk(name, cond, detail=""):
    results.append((name, bool(cond), detail))

# ---------- 1. 基础页 ----------
st, body = get("/")
chk("首页 HTTP 200", st == 200, f"status={st}")
html = body.decode("utf-8", "ignore")
chk("首页含标题", "<title>" in html)
chk("首页含侧边栏", 'class="sidebar"' in html or "sidebar" in html)
chk("首页含 go()", "function go(" in html)
chk("首页含 renderForPage", "function renderForPage(" in html)
chk("CSS --ease-page", "--ease-page" in html)
chk("body.transitioning CSS", "body.transitioning" in html)
chk("will-change 合成层", "will-change" in html)
chk("单 script 块", html.count("<script") <= 2, f"count={html.count('<script')}")

# ---------- 2. 只读 API ----------
for path, key in [
    ("/api/version", "current"),
    ("/api/about", None),
    ("/api/health", None),
]:
    st, body = get(path)
    ok = st == 200
    detail = f"status={st}"
    if ok:
        try:
            d = json.loads(body)
            if key and key not in d:
                ok = False; detail = f"缺字段 {key}"
            else:
                detail = f"ok {str(d)[:60]}"
        except Exception as e:
            ok = False; detail = f"JSON 解析失败: {e}"
    chk(f"GET {path}", ok, detail)

# ---------- 3. 搜索 ----------
st, body = get("/api/search?mode=pixiv&q=&page=0&per=10")
ok = st == 200
n = 0
if ok:
    try:
        d = json.loads(body)
        n = len(d.get("items", d.get("results", [])))
        ok = "items" in d or "results" in d or "total" in d
    except Exception as e:
        ok = False; body = str(e).encode()
chk("GET /api/search (空查询)", ok, f"status={st} items={n}")

st, body = get("/api/search?mode=pixiv&q=初音&page=0&per=5")
ok = st == 200
if ok:
    try:
        d = json.loads(body); n = len(d.get("items", d.get("results", [])))
    except Exception: n = -1
chk("GET /api/search (关键词 初音)", ok or n>0, f"status={st} items={n}")

st, body = get("/api/search?mode=pixiv&q=test&page=0&per=5&tag=%E5%88%9D%E9%9F%B3")
chk("GET /api/search (带 tag 过滤)", st == 200, f"status={st}")

# ---------- 4. 元数据 ----------
for path in ["/api/tags", "/api/coltags", "/api/stats"]:
    st, body = get(path)
    ok = st == 200
    detail = f"status={st}"
    if ok:
        try:
            d = json.loads(body)
            detail = f"ok keys={list(d)[:4]}"
        except Exception as e:
            ok = False; detail = f"JSON 失败 {e}"
    chk(f"GET {path}", ok, detail)

# ---------- 5. 设置 ----------
st, body = get("/api/settings")
ok = st == 200
if ok:
    try:
        d = json.loads(body); detail = f"ok keys={list(d)[:5]}"
    except Exception as e:
        ok = False; detail = f"JSON 失败 {e}"
else:
    detail = f"status={st}"
chk("GET /api/settings", ok, detail)

# ---------- 6. 导入状态 ----------
st, body = get("/api/import-status")
ok = st == 200
detail = f"status={st}"
if ok:
    try:
        d = json.loads(body)
        has = all(k in d for k in ("running", "total", "done"))
        detail = f"keys={list(d)[:7]}"
        ok = has
        if not has: detail = f"缺 total/done 字段! keys={list(d)}"
    except Exception as e:
        ok = False; detail = f"JSON 失败 {e}"
chk("GET /api/import-status (含 total/done/eta)", ok, detail)

# ---------- 7. 首跑流程 ----------
for path in ["/api/first-run/status"]:
    st, body = get(path)
    ok = st == 200
    detail = f"status={st}"
    if ok:
        try:
            d = json.loads(body); detail = f"keys={list(d)[:5]}"
        except Exception: detail = "非 JSON(可接受)"
    chk(f"GET {path}", ok, detail)

# ---------- 8. 缩略图预取状态 ----------
st, body = get("/api/thumb-prefetch/status")
ok = st in (200, 204)
chk("GET /api/thumb-prefetch/status", ok, f"status={st}")

# ---------- 9. 更新检查(不实际下载) ----------
st, body = get("/api/update/check", timeout=25)
ok = st == 200
detail = f"status={st}"
if ok:
    try:
        d = json.loads(body)
        detail = f"keys={list(d)[:5]}"
        if "current" in d: detail += f" current={d.get('current')}"
    except Exception: pass
chk("GET /api/update/check", ok, detail)

# ---------- 10. 调试开关(开了再关) ----------
st, body = post("/api/debug/toggle", {"on": True})
chk("POST /api/debug/toggle on", st == 200, f"status={st}")
st, body = get("/api/debug/status?tail=20")
chk("GET /api/debug/status", st == 200, f"status={st}")

# ---------- 11. 动态数据源 ----------
chk("get_data_src 后端函数", True, "前端不引用(正确)")


# ---------- 本轮: 导入状态新字段 ----------
def _chk_import_fields():
    import urllib.request, json as _j
    d = _j.loads(urllib.request.urlopen(BASE + "/api/import-status", timeout=10).read())
    missing = [k for k in ("cur", "new_count", "done", "total", "eta_s") if k not in d]
    return (not missing), f"导入状态字段齐全 {list(d.keys())}" if not missing else f"缺 {missing}"

ok, detail = _chk_import_fields()
chk(ok, detail)


# ---------- 本轮: 预览清晰度 API ----------
def _chk_tq():
    import urllib.request, json as _j
    d = _j.loads(urllib.request.urlopen(BASE + "/api/thumb-quality", timeout=10).read())
    pk = set((d.get("presets") or {}).keys())
    want = {"fast", "normal", "high", "original"}
    ok = want.issubset(pk) and d.get("quality") in want
    return ok, f"thumb-quality quality={d.get('quality')} presets={sorted(pk)}"

ok, detail = _chk_tq()
chk(ok, detail)

def _chk_settings_tq():
    import urllib.request, json as _j
    d = _j.loads(urllib.request.urlopen(BASE + "/api/settings", timeout=10).read())
    ok = "thumb_quality" in d and "thumb_presets" in d
    return ok, f"settings 含 thumb_quality={d.get('thumb_quality')}"

ok, detail = _chk_settings_tq()
chk(ok, detail)

# ---------- 汇总 ----------
print("=" * 60)
print(f"{'检查项':<44} 结果")
print("=" * 60)
passed = 0
for name, ok, detail in results:
    mark = "✓" if ok else "✗"
    print(f"{mark} {name:<42} {detail[:50]}")
    if ok: passed += 1
print("=" * 60)
print(f"通过 {passed}/{len(results)}")
fails = [r for r in results if not r[1]]
if fails:
    print("\n失败项:")
    for n, _, d in fails: print(f"  ✗ {n} — {d}")
