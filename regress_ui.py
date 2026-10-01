#!/usr/bin/env python3
"""PixivFavSearch UI 回归 — HTML/CSS/JS 完整性 + 页面切换动画检查"""
import sys, urllib.request, re
sys.stdout.reconfigure(encoding='utf-8')

BASE = "http://127.0.0.1:8897"
with urllib.request.urlopen(BASE + "/", timeout=15) as r:
    html = r.read().decode("utf-8", "ignore")

results = []
def chk(name, cond, detail=""):
    results.append((name, bool(cond), detail))

# ---------- 结构完整性 ----------
chk("单 script 块(嵌套会全失效)", html.count("<script") == 1, f"count={html.count('<script')}")
chk("页面容器 .page", ".page{" in html or ".page {" in html)
for pid in ["pg-search", "pg-fav", "pg-stats", "pg-settings"]:
    chk(f"页面存在 #{pid}", f'id="{pid}"' in html or f"id='{pid}'" in html)

# ---------- 侧边栏 ----------
chk("侧边栏容器", 'class="sidebar"' in html)
chk("侧边栏 hover 放大", ".sidebar:hover" in html)
chk("侧边栏图标 sbPop 动画", "@keyframes sbPop" in html)
for tip in ["搜索", "收藏夹", "统计", "设置"]:
    chk(f"侧边栏项「{tip}」", tip in html)

# ---------- 页面切换动画(本轮重点) ----------
chk("CSS 变量 --ease-page", "--ease-page" in html)
chk("ease-page 值正确", "cubic-bezier(.25,.1,.25,1)" in html)
chk(".page 用 ease-page", "var(--ease-page)" in html)
chk(".page 时长 300ms", "opacity .3s" in html and "transform .3s" in html)
chk(".page will-change 合成层", "will-change:opacity,transform" in html)
chk(".page backface-visibility", "backface-visibility:hidden" in html)
chk(".page.exit 左滑出", ".page.exit" in html and "translateX(-20px)" in html)
chk(".page.active 归位", ".page.active" in html and "translateX(0)" in html)
chk("过渡降模糊 body.transitioning", "body.transitioning" in html)
chk("过渡期 blur 降为 10px", "blur(10px)" in html)

# ---------- JS 逻辑 ----------
chk("go() 函数存在", "function go(" in html)
chk("renderForPage() 拆出", "function renderForPage(" in html)
chk("延迟渲染(320ms)", "320)" in html or "320," in html)
chk("go() 加 transitioning class", "classList.add('transitioning')" in html)
chk("go() 移除 transitioning", "classList.remove('transitioning')" in html)
chk("renderForPage 在动画后调用", "renderForPage(targetPage)" in html)
chk("旧页加 exit", "classList.add('exit')" in html)
chk("新页加 active", "classList.add('active')" in html)

# 确认渲染不再同步执行于 go() 主干
go_fn = html[html.find("function go("):html.find("function renderForPage(")] if "function go(" in html else ""
chk("go() 内无同步 renderWall", "renderWall()" not in go_fn.replace("renderForPage(targetPage)", ""),
    "渲染已移出动画路径")

# ---------- 后台渲染函数 ----------
for fn in ["renderWall", "renderFavs", "renderStats", "openFav"]:
    chk(f"{fn}() 存在", f"function {fn}(" in html)

# ---------- 分页条 ----------
chk("分页条元素", 'id="pagination"' in html)

# ---------- API 未被破坏 ----------
for ep in ["/api/search", "/api/import", "/api/import-status", "/api/stats"]:
    chk(f"前端引用 {ep}", ep in html)


# ---------- 导入进度可见性(本轮修复) ----------
chk("前端用 sd.total (真实总数)", "sd.total" in html)
chk("前端用 sd.done (已导入)", "sd.done" in html)
chk("前端用 sd.eta_s (剩余秒)", "sd.eta_s" in html)
chk("进度文案 共 Y 幅", "幅 · '+" in html or "幅 · " in html)
chk("灵动岛显示进度", "导入中</b> '+sd.done" in html or "导入中</b> " in html)
chk("首跑向导去硬编码 /20", "Math.min(95,s.count/20)" not in html or "s.total>0" in html)


# ---------- 本轮修复: 键盘 / 导入面板 / 托盘路径 ----------
chk("Home/End 用 currentScrollEl(非 window)", "currentScrollEl()" in html and "window.scrollTo({top:0" not in html)
chk("currentScrollEl 函数已定义", "function currentScrollEl()" in html)
chk("撤回键 Ctrl+Z", "e.key==='z'" in html)
chk("撤回键 Alt+Left", "e.altKey&&e.key==='ArrowLeft'" in html)
chk("撤回键 Backspace", "e.key==='Backspace'" in html)
chk("导入面板 HTML 存在", 'id="imp-panel"' in html)
chk("导入面板 进度条", 'id="imp-fill"' in html)
chk("导入面板 阶段文案", 'id="imp-stage"' in html)
chk("导入面板 结果提醒", "impPanelDone(" in html)
chk("导入面板 失败提醒", "impPanelErr(" in html)
chk("导入面板 关闭按钮", "function impPanelClose()" in html)
chk("导入面板 卡住提示", "stall===90" in html)
chk("导入面板 自动收起(9s)", "},9000)" in html)
chk("导入进度读 sd.cur", "sd.cur" in html)
chk("导入完成读 new_count", "sd.new_count" in html)
chk("导入完成刷新统计", "renderStats()" in html)
chk("导入面板 CSS 样式", ".imp-panel{" in html)


# ---------- 撤销栈(本轮) ----------
chk("撤销栈变量 undoStack", "let undoStack=[]" in html)
chk("快照函数 snapState", "function snapState()" in html)
chk("入栈函数 pushUndo", "function pushUndo()" in html)
chk("恢复函数 restoreState", "async function restoreState(st)" in html)
chk("撤销入口 doUndo", "function doUndo()" in html)
chk("撤销提示 updateUndoHint", "function updateUndoHint()" in html)
chk("撤销 Toast", "function toastUndo(" in html)
chk("Ctrl+Z 接 doUndo", "e.preventDefault();doUndo();return;" in html)
chk("侧键接 doUndo", "_sideBtnHandled=Date.now();" in html and "doUndo();" in html)
chk("入栈点 >= 8 个", html.count("pushUndo();") >= 8)
chk("撤销按钮 DOM", 'id="undo-hint"' in html)
chk("撤销 Toast CSS", ".undo-toast{" in html)

# ---------- 预览清晰度(本轮) ----------
chk("清晰度网格 DOM", 'id="tq-grid"' in html)
chk("清晰度 tqLoad", "async function tqLoad()" in html)
chk("清晰度 tqRender", "function tqRender()" in html)
chk("清晰度 tqApply", "async function tqApply(" in html)
chk("清晰度 CSS", ".tq-item{" in html)
chk("启动加载 tqLoad", "tqLoad();" in html)

# ---------- 汇总 ----------
print("=" * 62)
print(f"{'检查项':<44} 结果")
print("=" * 62)
passed = 0
for name, ok, detail in results:
    mark = "✓" if ok else "✗"
    print(f"{mark} {name:<42} {detail[:40]}")
    if ok: passed += 1
print("=" * 62)
print(f"通过 {passed}/{len(results)}")
fails = [r for r in results if not r[1]]
if fails:
    print("\n失败项:")
    for n, _, d in fails: print(f"  ✗ {n} — {d}")
