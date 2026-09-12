#!/usr/bin/env python3
"""Replace INDEX HTML in pix_search_server.py with sidebar layout version"""
import re

filepath = "C:/temp/Hermes/PixivFavSearch/pix_search_server.py"

with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Find the INDEX block
start_marker = 'INDEX = r"""<!doctype html>'
end_marker = '"""\n\n# --- 可复用的启动/停止函数'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print(f"ERROR: Could not find INDEX boundaries. start={start_idx}, end={end_idx}")
    exit(1)

print(f"Found INDEX at char {start_idx} to {end_idx}")

new_index = r'''INDEX = r"""<!doctype html><html lang=zh><meta charset=utf-8><title>PixivFavSearch</title>
<style>
 :root{
  --bg:#F2F2F7;--card:#FFFFFF;--text:#1C1C1E;--sub:#8E8E93;--accent:#ef9eff;--accent-ink:#2b0030;
  --field-bg:#FFFFFF;--field-border:#E5E5EA;--topbar:rgba(242,242,247,.82);
  --shadow:0 2px 10px rgba(0,0,0,.05);--shadow-hover:0 12px 28px rgba(0,0,0,.13);
  --sidebar-bg:#1C1C1E;--sidebar-text:#98989F;--sidebar-active:#ef9eff;
 }
 @media (prefers-color-scheme: dark){
  :root{
   --bg:#000000;--card:#1C1C1E;--text:#F2F2F7;--sub:#98989F;--accent:#ef9eff;--accent-ink:#2b0030;
   --field-bg:#2C2C2E;--field-border:#38383A;--topbar:rgba(0,0,0,.72);
   --shadow:0 2px 10px rgba(0,0,0,.45);--shadow-hover:0 12px 30px rgba(0,0,0,.65);
   --sidebar-bg:#000000;--sidebar-text:#888888;--sidebar-active:#ef9eff;
  }
 }
 body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);margin:0;padding:0;transition:background .3s,color .3s;display:flex;height:100vh;overflow:hidden}
 /* -- 侧边栏 -- */
 .sidebar{width:60px;min-width:60px;background:var(--sidebar-bg);display:flex;flex-direction:column;align-items:center;padding:16px 0;gap:8px;z-index:100;border-right:1px solid rgba(255,255,255,.06)}
 .sidebar-btn{width:44px;height:44px;border-radius:12px;border:none;background:transparent;color:var(--sidebar-text);font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .2s;position:relative}
 .sidebar-btn:hover{background:rgba(255,255,255,.08);color:#fff}
 .sidebar-btn.active{background:linear-gradient(135deg,rgba(239,158,255,.25),rgba(199,125,255,.18));color:var(--sidebar-active)}
 .sidebar-btn .tt{position:absolute;left:56px;top:50%;transform:translateY(-50%);background:rgba(0,0,0,.85);color:#fff;font-size:12px;padding:5px 10px;border-radius:6px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .15s}
 .sidebar-btn:hover .tt{opacity:1}
 .sidebar-spacer{flex:1}
 /* -- 主内容区 -- */
 .main{flex:1;overflow-y:auto;padding:24px 20px 60px;position:relative}
 .page-container{display:none}
 .page-container.active{display:block}
 /* -- 顶部横幅(pixiv 风格,可替换大图) -- */
 .banner{position:relative;height:150px;border-radius:16px 16px 0 0;overflow:hidden;background:
   radial-gradient(120% 140% at 15% 20%,color-mix(in srgb,var(--accent) 30%,transparent) 0%,transparent 55%),
   radial-gradient(120% 140% at 85% 80%,color-mix(in srgb,#c77dff 35%,transparent) 0%,transparent 60%),
   linear-gradient(135deg,#2a2a31,#3a2c46 55%,#4a2c58)}
 .banner img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;will-change:transform}
 .banner img.adj{cursor:grab;transition:none}
 .banner img.adj.drag{cursor:grabbing}
 .banner-shade{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.02) 45%,rgba(0,0,0,.42));pointer-events:none}
 .banner .banner-mark{position:absolute;top:12px;left:14px;display:inline-flex;align-items:center;gap:7px;color:rgba(255,255,255,.92);font-size:12px;font-weight:700;letter-spacing:.3px;background:rgba(0,0,0,.32);padding:5px 12px;border-radius:20px;backdrop-filter:blur(8px);pointer-events:none}
 .banner .banner-mark svg{width:15px;height:15px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.3))}
 /* -- 顶部按钮栏 -- */
 .mode-switch{position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:3;display:flex;gap:4px;background:rgba(0,0,0,.38);padding:4px;border-radius:22px;backdrop-filter:blur(10px)}
 .mode-btn{border:none;cursor:pointer;font-size:12px;font-weight:700;color:rgba(255,255,255,.75);background:transparent;padding:6px 16px;border-radius:18px;transition:background .2s,color .2s,transform .18s cubic-bezier(.34,1.56,.64,1)}
 .mode-btn:hover{color:#fff;transform:scale(1.05)}
 .mode-btn.active{background:linear-gradient(135deg,#ef9eff,#c77dff);color:#2b0030;box-shadow:0 2px 10px rgba(0,0,0,.35)}
 .mode-btn:active{transform:scale(.9)}
 .import-btn{border:none;cursor:pointer;font-size:12px;font-weight:700;color:#2b0030;background:linear-gradient(135deg,#ef9eff,#c77dff);padding:6px 14px;border-radius:18px;box-shadow:0 2px 10px rgba(0,0,0,.35);transition:background .2s,transform .18s cubic-bezier(.34,1.56,.64,1),opacity .2s}
 .import-btn:hover{transform:scale(1.06);box-shadow:0 4px 14px rgba(0,0,0,.4)}
 .import-btn:active{transform:scale(.9)}
 .import-btn.loading{opacity:.65;cursor:wait}
 .banner-btns{position:absolute;top:10px;right:10px;z-index:3;display:none;gap:6px}
 .banner:hover .banner-btns{display:flex}
 .swap-btn{display:inline-flex;align-items:center;gap:6px;border:none;cursor:pointer;font-size:12px;font-weight:600;color:#fff;background:rgba(0,0,0,.45);padding:6px 13px;border-radius:20px;backdrop-filter:blur(8px);transition:background .2s,transform .18s cubic-bezier(.34,1.56,.64,1)}
 .swap-btn:hover{background:rgba(0,0,0,.68);transform:scale(1.06)}
 .swap-btn:active{transform:scale(.92)}
 .adj-done{position:absolute;bottom:12px;right:12px;z-index:4;display:none;align-items:center;gap:6px;border:none;cursor:pointer;font-size:13px;font-weight:700;color:#fff;background:linear-gradient(135deg,#ef9eff,#c77dff);padding:8px 18px;border-radius:22px;box-shadow:0 4px 14px rgba(0,0,0,.35);transition:transform .18s cubic-bezier(.34,1.56,.64,1)}
 .adj-done:hover{transform:scale(1.06)}
 .hd-row{position:relative;display:flex;align-items:flex-end;gap:14px;margin:-30px 16px 4px;z-index:2}
 .avatar{position:relative;width:64px;height:64px;border-radius:50%;background:var(--card);box-shadow:0 4px 14px rgba(0,0,0,.28),0 0 0 3px var(--card);flex-shrink:0;display:flex;align-items:center;justify-content:center}
 .avatar-ph{width:32px;height:32px;color:var(--sub);opacity:.6}
 .avatar img{position:relative;width:100%;height:100%;border-radius:50%;object-fit:cover;display:block;will-change:transform}
 .avatar img.adj{cursor:grab;transition:none}
 .avatar img.adj.drag{cursor:grabbing}
 .avatar-swap{position:absolute;bottom:-2px;width:26px;height:26px;border-radius:50%;border:none;cursor:pointer;font-size:13px;background:var(--accent);color:var(--accent-ink);display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,.3);transition:transform .18s cubic-bezier(.34,1.56,.64,1);opacity:0}
 .avatar:hover .avatar-swap{opacity:1}
 .avatar-swap:hover{transform:scale(1.15)}
 .avatar-swap:active{transform:scale(.9)}
 .avatar-swap.swap-photo{right:-2px}
 .avatar-swap.swap-move{left:-2px}
 .adj-done-av{position:absolute;top:-6px;right:-6px;z-index:5;width:30px;height:30px;border-radius:50%;border:none;cursor:pointer;font-size:14px;font-weight:800;background:var(--accent);color:var(--accent-ink);display:none;align-items:center;justify-content:center;box-shadow:0 3px 10px rgba(0,0,0,.4);transition:transform .18s cubic-bezier(.34,1.56,.64,1)}
 .adj-done-av:hover{transform:scale(1.15)}
 /* -- 裁剪弹窗(pixiv 式框选) -- */
 .crop-modal{position:fixed;inset:0;z-index:999;background:rgba(0,0,0,.6);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:20px}
 .crop-box{background:var(--card);border-radius:18px;padding:20px;width:min(92vw,760px);box-shadow:0 20px 60px rgba(0,0,0,.45);animation:popIn .3s cubic-bezier(.34,1.56,.64,1) both}
 .crop-title{font-size:15px;font-weight:700;margin:0 0 12px;color:var(--text)}
 .crop-stage{position:relative;width:100%;height:420px;background:#141416;border-radius:12px;overflow:hidden;user-select:none;touch-action:none}
 .crop-stage img{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);max-width:none;cursor:grab;user-select:none;-webkit-user-drag:none;will-change:transform}
 .crop-stage img.drag{cursor:grabbing}
 .crop-frame{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);border:1.5px solid rgba(255,255,255,.95);box-shadow:0 0 0 9999px rgba(0,0,0,.55);pointer-events:none;z-index:2}
 .crop-hint{position:absolute;left:50%;bottom:10px;transform:translateX(-50%);color:rgba(255,255,255,.9);font-size:12px;background:rgba(0,0,0,.55);padding:4px 14px;border-radius:14px;pointer-events:none;white-space:nowrap;z-index:3}
 .crop-bar{display:flex;justify-content:flex-end;gap:10px;margin-top:14px}
 .crop-btn{border:none;cursor:pointer;font-size:14px;font-weight:700;padding:9px 20px;border-radius:12px;transition:transform .18s cubic-bezier(.34,1.56,.64,1)}
 .crop-btn:hover{transform:scale(1.05)}
 .crop-btn:active{transform:scale(.93)}
 .crop-btn.cancel{background:var(--field-bg);color:var(--text);border:1px solid var(--field-border)}
 .crop-btn.ok{background:var(--accent);color:var(--accent-ink)}
 .hd-icon{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border-radius:13px;background:linear-gradient(135deg,#ef9eff 0%,#c77dff 55%,#a95cff 100%);flex-shrink:0;box-shadow:0 5px 14px color-mix(in srgb,var(--accent) 45%,transparent),inset 0 1px 0 rgba(255,255,255,.5);transition:transform .25s cubic-bezier(.34,1.56,.64,1)}
 .hd-icon:hover{transform:scale(1.08) rotate(-4deg)}
 .hd-icon svg{width:21px;height:21px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.25))}
 .hd-title{font-size:22px;font-weight:700;letter-spacing:-.3px;color:var(--text);margin:0}
 .hd-title span{background:linear-gradient(135deg,var(--accent),#c77dff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
 .hd-titles{display:flex;flex-direction:column;min-width:0;padding-bottom:2px}
 .hd-sub{font-size:11px;color:var(--sub);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 .hd-badge{font-size:11px;font-weight:600;color:var(--sub);background:var(--field-bg);padding:2px 10px;border-radius:20px;border:1px solid var(--field-border);margin-left:auto;display:flex;align-items:center;gap:6px;margin-bottom:6px}
 .hd-badge::before{content:'';display:inline-block;width:6px;height:6px;border-radius:50%;background:#34C759;animation:pulse 2.2s ease-in-out infinite}
 @keyframes pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(52,199,89,.5)}50%{opacity:.55;box-shadow:0 0 0 4px rgba(52,199,89,0)}}
 .bar{display:flex;gap:8px;margin:8px 0 0;flex-wrap:wrap;align-items:stretch}
 /* -- 自定义下拉容器 -- */
 .dd-container{position:relative;flex:0 0 auto;min-width:170px;max-width:260px}
 .dd-trigger{display:flex;align-items:center;gap:6px;padding:10px 12px;border-radius:12px;border:1px solid var(--field-border);background:var(--field-bg);cursor:pointer;transition:transform .2s cubic-bezier(.34,1.56,.64,1),box-shadow .2s,border-color .2s;user-select:none;height:100%;box-sizing:border-box;position:relative;z-index:2}
 .dd-trigger:hover{transform:scale(1.015);border-color:var(--accent)}
 .dd-trigger:focus-within{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
 .dd-text{flex:1;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)}
 .dd-arrow{font-size:10px;color:var(--sub);transition:transform .2s}
 .dd-container.open .dd-arrow{transform:rotate(180deg)}
 .dd-container.open .dd-trigger{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
 .dd-menu{position:absolute;top:calc(100% + 6px);left:0;right:0;max-height:320px;overflow-y:auto;background:var(--card);border-radius:14px;border:1px solid var(--field-border);box-shadow:0 8px 30px rgba(0,0,0,.2);z-index:100;opacity:0;transform:translateY(-8px) scale(.96);pointer-events:none;transition:opacity .2s,transform .22s cubic-bezier(.34,1.56,.64,1)}
 .dd-container.open .dd-menu{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}
 .dd-opt{padding:10px 14px;font-size:13px;cursor:pointer;transition:background .12s,color .12s;color:var(--text);border-bottom:1px solid color-mix(in srgb,var(--field-border) 40%,transparent)}
 .dd-opt:last-child{border-bottom:none}
 .dd-opt:hover{background:color-mix(in srgb,var(--accent) 15%,transparent)} 
 .dd-opt.sel{background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);font-weight:600}
 .dd-opt .oc{float:right;color:var(--sub);font-size:11px;font-weight:400}
 .dd-opt.sel .oc{color:color-mix(in srgb,var(--accent) 60%,transparent)}
 /* -- -- */
 input{flex:1;min-width:220px;padding:11px 16px;border-radius:12px;border:1px solid var(--field-border);background:var(--field-bg);color:var(--text);font-size:15px;box-shadow:0 1px 4px rgba(0,0,0,.06);transition:transform .2s cubic-bezier(.34,1.56,.64,1),box-shadow .2s,border-color .2s}
 input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent);transform:scale(1.01)}
 input:hover{transform:scale(1.015)}
 button{padding:11px 24px;border-radius:12px;border:0;background:var(--accent);color:var(--accent-ink);font-size:15px;font-weight:700;cursor:pointer;transition:transform .18s cubic-bezier(.34,1.56,.64,1),background .15s,box-shadow .2s}
 button:hover{background:color-mix(in srgb,var(--accent) 85%,#000);transform:translateY(-1px) scale(1.05);box-shadow:0 6px 16px color-mix(in srgb,var(--accent) 45%,transparent)}
 button:active{transform:scale(.88)}
 #meta{color:var(--sub);font-size:13px;margin:12px 2px 14px}
 #hint{color:#34C759;font-size:12px;margin:8px 2px 0;min-height:16px;font-weight:500}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:16px}
 .card{background:var(--card);border-radius:16px;overflow:hidden;box-shadow:var(--shadow);border:1px solid color-mix(in srgb,var(--field-border) 55%,transparent);transition:transform .22s cubic-bezier(.34,1.56,.64,1),box-shadow .22s,border-color .22s;animation:popIn .4s cubic-bezier(.34,1.56,.64,1) both;content-visibility:auto;contain-intrinsic-size:280px}
 .card:hover{box-shadow:var(--shadow-hover);transform:translateY(-5px) scale(1.02);will-change:transform}
 .card:active{transform:scale(.97)}
 .card img{width:100%;height:175px;object-fit:cover;background:var(--field-bg);display:block;transition:transform .35s cubic-bezier(.34,1.56,.64,1);will-change:transform;backface-visibility:hidden}
 .card:hover img{transform:scale(1.06)}
 .card .tt{padding:10px 12px 2px;font-size:13px;font-weight:600;line-height:1.4;height:40px;overflow:hidden;color:var(--text)}
 .card .tt mark{background:color-mix(in srgb,var(--accent) 45%,transparent);color:inherit;border-radius:3px;padding:0 2px;font-weight:700}
 .card .au{color:var(--sub);font-size:11px;padding:0 12px 8px}
 .card .tg{padding:0 12px 10px;font-size:10px;font-weight:600;color:var(--accent);line-height:1.5;height:30px;overflow:hidden;transition:transform .2s cubic-bezier(.34,1.56,.64,1),color .2s}
 .card:hover .tg{transform:translateY(-1px);color:color-mix(in srgb,var(--accent) 82%,#000)}
 .card .go{display:block;margin:0 12px 12px;padding:9px 0;text-align:center;border-radius:10px;background:var(--accent);color:var(--accent-ink);font-size:13px;font-weight:700;transition:transform .18s cubic-bezier(.34,1.56,.64,1),background .15s,box-shadow .2s}
 .card .go:hover{background:color-mix(in srgb,var(--accent) 85%,#000);transform:scale(1.04);box-shadow:0 4px 12px color-mix(in srgb,var(--accent) 45%,transparent)}
 .card .go:active{transform:scale(.9)}
 .card .fav-btn{display:block;margin:0 12px 8px;padding:7px 0;text-align:center;border-radius:10px;background:var(--field-bg);color:var(--text);font-size:12px;font-weight:600;border:1px solid var(--field-border);cursor:pointer;transition:all .15s}
 .card .fav-btn:hover{border-color:var(--accent);color:var(--accent)}
 .card .fav-btn.in-fav{background:color-mix(in srgb,var(--accent) 15%,transparent);border-color:var(--accent);color:var(--accent)}
 a{text-decoration:none;color:inherit}
 /* 悬浮回主页按钮(低调) */
 #home-btn{position:fixed;bottom:18px;right:18px;z-index:9999;width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.1);color:var(--sub);font-size:15px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s;box-shadow:none;opacity:.4;backdrop-filter:blur(4px)}
 #home-btn:hover{opacity:.9;color:#ef9eff;border-color:rgba(239,158,255,.5)}
 #home-btn .ttip{position:absolute;right:40px;white-space:nowrap;background:rgba(0,0,0,.8);padding:3px 8px;border-radius:6px;font-size:11px;border:1px solid rgba(255,255,255,.1);opacity:0;pointer-events:none;transition:opacity .18s;color:var(--fg)}
 #home-btn:hover .ttip{opacity:1}
 .empty{color:var(--sub);padding:60px 0;text-align:center;font-size:14px;animation:popIn .4s cubic-bezier(.34,1.56,.64,1) both}
 @keyframes popIn{0%{opacity:0;transform:translateY(12px)}60%{opacity:1;transform:translateY(-4px)}100%{opacity:1;transform:translateY(0)}}
 ::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background:var(--sub);border-radius:6px;border:2px solid var(--bg)}
 /* -- 收藏夹页 -- */
 .fav-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}
 .fav-header h2{font-size:20px;font-weight:700;margin:0}
 .fav-header .actions{display:flex;gap:8px}
 .fav-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}
 .fav-card{background:var(--card);border-radius:14px;padding:20px;box-shadow:var(--shadow);border:1px solid color-mix(in srgb,var(--field-border) 55%,transparent);cursor:pointer;transition:all .2s;position:relative}
 .fav-card:hover{box-shadow:var(--shadow-hover);transform:translateY(-3px) scale(1.01)}
 .fav-card .tag-name{font-size:15px;font-weight:600;margin-bottom:6px;word-break:break-all}
 .fav-card .tag-count{font-size:12px;color:var(--sub)}
 .fav-card .del-btn{position:absolute;top:10px;right:10px;width:24px;height:24px;border-radius:50%;border:none;background:transparent;color:var(--sub);font-size:14px;cursor:pointer;opacity:0;transition:all .15s;display:flex;align-items:center;justify-content:center}
 .fav-card:hover .del-btn{opacity:1}
 .fav-card .del-btn:hover{background:rgba(255,69,58,.15);color:#FF453A}
 .fav-detail-header{display:flex;align-items:center;gap:12px;margin-bottom:16px}
 .fav-detail-header .back-btn{width:36px;height:36px;border-radius:10px;border:1px solid var(--field-border);background:var(--field-bg);color:var(--text);font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s}
 .fav-detail-header .back-btn:hover{border-color:var(--accent);color:var(--accent)}
 .fav-detail-header h2{font-size:18px;font-weight:700;margin:0}
 /* -- 设置页 -- */
 .settings-section{background:var(--card);border-radius:14px;padding:20px;margin-bottom:16px;box-shadow:var(--shadow);border:1px solid color-mix(in srgb,var(--field-border) 55%,transparent)}
 .settings-section h3{font-size:15px;font-weight:700;margin:0 0 4px}
 .settings-section .desc{font-size:12px;color:var(--sub);margin-bottom:14px;line-height:1.5}
 .settings-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
 .settings-row input{flex:1;min-width:200px}
 .settings-row .status{font-size:12px;color:#34C759;font-weight:500}
 .settings-row .status.error{color:#FF453A}
 .modal-overlay{position:fixed;inset:0;z-index:998;background:rgba(0,0,0,.5);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;padding:20px}
 .modal-overlay.show{display:flex}
 .modal-box{background:var(--card);border-radius:16px;padding:24px;width:min(92vw,400px);box-shadow:0 20px 60px rgba(0,0,0,.4);animation:popIn .25s cubic-bezier(.34,1.56,.64,1) both}
 .modal-box h3{font-size:16px;font-weight:700;margin:0 0 14px}
 .modal-box input{width:100%;margin-bottom:12px}
 .modal-box .modal-actions{display:flex;justify-content:flex-end;gap:10px}
 /* -- 标签选择器弹窗 -- */
 .tag-picker{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;max-height:200px;overflow-y:auto}
 .tag-picker .tag-chip{padding:6px 14px;border-radius:20px;border:1px solid var(--field-border);background:var(--field-bg);font-size:12px;cursor:pointer;transition:all .15s}
 .tag-picker .tag-chip:hover{border-color:var(--accent)}
 .tag-picker .tag-chip.selected{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
</style>
<!-- 侧边栏 -->
<nav class=sidebar>
 <button class="sidebar-btn active" data-page="search" onclick="switchPage('search')">🔍<span class=tt data-l data-zh="搜索" data-en="Search">搜索</span></button>
 <button class="sidebar-btn" data-page="favorites" onclick="switchPage('favorites')">⭐<span class=tt data-l data-zh="收藏夹" data-en="Favorites">收藏夹</span></button>
 <button class="sidebar-btn" data-page="settings" onclick="switchPage('settings')">⚙️<span class=tt data-l data-zh="设置" data-en="Settings">设置</span></button>
 <div class=sidebar-spacer></div>
</nav>
<!-- 主内容区 -->
<div class=main>
 <!-- 搜索页 -->
 <div class="page-container active" id="page-search">
<header class=topbar>
 <div class=banner id=banner>
  <img id=banner-img src=/assets/banner alt='' onerror="this.style.display='none'">
  <div class=banner-shade></div>
  <div class=banner-mark><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z'/></svg><span id=banner-mark-text data-l data-zh="Pixiv 书签搜索" data-en="PixivFavSearch">Pixiv 书签搜索</span></div>
  <div class=mode-switch>
   <button class="mode-btn active" id=btn-pixiv onclick="switchMode('pixiv')">📚 Pixiv</button>
   <button class="lang-btn" id=btn-lang onclick="toggleLang()">中 / EN</button>
   <button class=import-btn id=btn-import onclick="doImport()" data-l data-zh="📥 导入/更新收藏" data-en="📥 Import / Update">📥 导入/更新收藏</button>
  </div>
  <div class=banner-btns>
   <button class=swap-btn onclick=pick('banner') data-l data-zh="🖼 更换横幅" data-en="🖼 Change Banner">🖼 更换横幅</button>
   <button class=swap-btn onclick=enterAdj('banner') data-l data-zh="✋ 调整位置" data-en="✋ Adjust Position">✋ 调整位置</button>
  </div>
  <button class=adj-done id=done-banner onclick=doneAdj('banner') data-l data-zh="✓ 完成" data-en="✓ Done">✓ 完成</button>
 </div>
 <div class=hd-row>
  <div class=avatar id=avatar>
   <svg class=avatar-ph viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round'><circle cx='12' cy='8' r='4'/><path d='M4 21c0-4.2 3.6-6.4 8-6.4s8 2.2 8 6.4'/></svg>
   <img id=avatar-img src=/assets/avatar alt='' onerror="this.style.display='none'">
   <button class=avatar-swap swap-photo onclick=pick('avatar') title=更换头像 data-l-t data-zh-t="更换头像" data-en-t="Change Avatar">📷</button>
   <button class=avatar-swap swap-move onclick=enterAdj('avatar') title=调整位置 data-l-t data-zh-t="调整位置" data-en-t="Adjust Position">✋</button>
   <button class=adj-done-av id=done-avatar onclick=doneAdj('avatar') title=完成 data-l-t data-zh-t="完成" data-en-t="Done">✓</button>
  </div>
  <div class=hd-titles>
   <div class=hd-title><span id=hd-title-text data-l data-zh="Pixiv 书签搜索" data-en="PixivFavSearch">Pixiv 书签搜索</span></div>
   <div class=hd-sub id=hd-sub-text data-l data-zh="本地 · 全部收藏 · 标题/标签/简介全字段搜索 · 假名→罗马音跨语言" data-en="Local · All bookmarks · Full-text title/tag/desc · kana→romaji">本地 · 全部收藏 · 标题/标签/简介全字段搜索 · 假名→罗马音跨语言</div>
  </div>
  <div class=hd-badge data-l data-zh="本地运行中" data-en="Running locally">本地运行中</div>
 </div>
 <div class=bar>
  <div class=dd-container id=dd-coltag>
   <select id=coltag onchange="go()" hidden><option value="" data-l data-zh="全部收藏标签" data-en="All coltags">全部收藏标签</option></select>
   <div class=dd-trigger role=button tabindex=0><span class=dd-text id=coltag-text data-l data-zh="全部收藏标签" data-en="All coltags">全部收藏标签</span><span class=dd-arrow>▾</span></div>
   <div class=dd-menu id=coltag-menu></div>
  </div>
  <div class=dd-container id=dd-tag>
   <select id=tag onchange="go()" hidden><option value="" data-l data-zh="全部作品标签(不限)" data-en="All tags (any)">全部作品标签(不限)</option></select>
   <div class=dd-trigger role=button tabindex=0><span class=dd-text id=tag-text data-l data-zh="全部作品标签(不限)" data-en="All tags (any)">全部作品标签(不限)</span><span class=dd-arrow>▾</span></div>
   <div class=dd-menu id=tag-menu></div>
  </div>
  <input id=q data-l-ph data-zh="输入关键词，如: ibuki / 水着 / ブルアカ / Plana ..." data-en="Search keyword, e.g. ibuki / swimsuit / Plana ..." placeholder="输入关键词，如: ibuki / 水着 / ブルアカ / Plana ..." onkeydown="if(event.key==='Enter')go()">
  <button onclick="go()" data-l data-zh="搜索" data-en="Search">搜索</button>
  </div>
  <div id=hint></div>
</header>
<div id=crop-modal class=crop-modal>
 <div class=crop-box>
  <div class=crop-title data-l data-zh="✂ 裁剪图片 — 框内就是要显示的区域" data-en="✂ Crop Image — area inside frame is what shows">✂ 裁剪图片 — 框内就是要显示的区域</div>
  <div class=crop-stage id=crop-stage>
   <img id=crop-img alt=''>
   <div class=crop-frame id=crop-frame></div>
   <div class=crop-hint data-l data-zh="拖动图片选位置 · 滚轮缩放 · 框内 = 最终显示" data-en="Drag to position · Scroll to zoom · Inside frame = final view">拖动图片选位置 · 滚轮缩放 · 框内 = 最终显示</div>
  </div>
  <div class=crop-bar>
   <button class="crop-btn cancel" onclick=cropCancel() data-l data-zh="取消" data-en="Cancel">取消</button>
   <button class="crop-btn ok" onclick=cropConfirm() data-l data-zh="✓ 确认裁剪" data-en="✓ Confirm Crop">✓ 确认裁剪</button>
  </div>
 </div>
</div>
<div id=meta></div><div id=grid class=grid></div>
<div id=demo-bar data-l data-zh="🎨 当前为效果预览，导入收藏后即可正常使用" data-en="🎨 Preview mode - import your bookmarks to use" style="display:none;position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:60;background:rgba(18,18,32,.78);backdrop-filter:blur(8px);color:#fff;font-size:13px;font-weight:600;padding:10px 20px;border-radius:22px;box-shadow:0 6px 18px rgba(0,0,0,.4);pointer-events:none;white-space:nowrap;max-width:92vw;text-align:center">🎨 当前为效果预览，导入收藏后即可正常使用</div>
<div id=import-tip style="display:none;position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:59;background:rgba(40,40,80,.85);backdrop-filter:blur(8px);color:#fff;font-size:12px;padding:8px 16px;border-radius:18px;box-shadow:0 4px 12px rgba(0,0,0,.3);pointer-events:none;white-space:nowrap;max-width:92vw;text-align:center" data-l data-zh="💡 首次导入需在 WebView2 中登录一次 Pixiv，之后自动保存登录态" data-en="💡 First import requires logging into Pixiv in WebView2, login persists afterwards">💡 首次导入需在 WebView2 中登录一次 Pixiv，之后自动保存登录态</div>
<button id=home-btn title="回到本站主页" data-l-t data-zh-t="回到本站主页" data-en-t="Back to homepage" onclick="location.href='/'"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 10.5L12 3l9 7.5'/><path d='M5 9.5V21h14V9.5'/></svg><span class=ttip data-l data-zh="🏠 回到本站" data-en="🏠 Home">🏠 回到本站</span></button>
 </div><!-- /page-search -->

 <!-- 收藏夹页 -->
 <div class="page-container" id="page-favorites">
  <div class="fav-header" id="fav-list-header">
   <h2 data-l data-zh="收藏夹" data-en="Favorites">收藏夹</h2>
   <div class=actions>
    <button onclick="showCreateTagModal()" data-l data-zh="➕ 新建标签" data-en="➕ New Tag">➕ 新建标签</button>
   </div>
  </div>
  <div class="fav-detail-header" id="fav-detail-header" style="display:none">
   <button class=back-btn onclick="showFavList()">←</button>
   <h2 id="fav-detail-title">Tag</h2>
  </div>
  <div class=fav-grid id=fav-grid></div>
  <div id=fav-works style="display:none">
   <div id=fav-works-grid class=grid style="margin-top:16px"></div>
  </div>
 </div><!-- /page-favorites -->

 <!-- 设置页 -->
 <div class="page-container" id="page-settings">
  <h2 style="font-size:20px;font-weight:700;margin:0 0 20px" data-l data-zh="设置" data-en="Settings">设置</h2>
  <!-- 代理配置 -->
  <div class=settings-section>
   <h3 data-l data-zh="🌐 代理配置" data-en="🌐 Proxy">🌐 代理配置</h3>
   <div class=desc data-l data-zh="设置 HTTP 代理地址，用于连接 Pixiv" data-en="HTTP proxy for connecting to Pixiv">设置 HTTP 代理地址，用于连接 Pixiv</div>
   <div class=settings-row>
    <input id=proxy-input placeholder="http://127.0.0.1:10808">
    <button onclick="saveProxy()" data-l data-zh="保存" data-en="Save">保存</button>
    <span class=status id=proxy-status></span>
   </div>
  </div>
  <!-- Cookie 管理 -->
  <div class=settings-section>
   <h3 data-l data-zh="🍪 Cookie 管理" data-en="🍪 Cookie">🍪 Cookie 管理</h3>
   <div class=desc data-l data-zh="当前登录状态" data-en="Current login status">当前登录状态</div>
   <div class=settings-row>
    <span id=cookie-status style="flex:1;font-size:13px;color:var(--sub)">-</span>
    <button onclick="clearCookies()" data-l data-zh="清除并重新登录" data-en="Clear & Re-login">清除并重新登录</button>
   </div>
  </div>
  <!-- 数据管理 -->
  <div class=settings-section>
   <h3 data-l data-zh="💾 数据管理" data-en="💾 Data">💾 数据管理</h3>
   <div class=desc data-l data-zh="管理本地收藏数据" data-en="Manage local bookmark data">管理本地收藏数据</div>
   <div class=settings-row>
    <span id=data-status style="flex:1;font-size:13px;color:var(--sub)">-</span>
    <button onclick="clearAllData()" data-l data-zh="清空所有收藏" data-en="Clear All Data">清空所有收藏</button>
   </div>
  </div>
  <!-- 关于 -->
  <div class=settings-section>
   <h3 data-l data=zh="ℹ️ 关于" data-en="ℹ️ About">ℹ️ 关于</h3>
   <div class=desc>
    <span data-l data-zh="版本" data-en="Version">版本</span>: <span id=about-version>1.0.0</span><br>
    <a id=about-link href="https://github.com/Hzm66647/PixivFavSearch" target=_blank style="color:var(--accent)">GitHub</a>
   </div>
   <div class=settings-row>
    <button onclick="checkUpdate()" data-l data-zh="检查更新" data-en="Check Update">检查更新</button>
    <span class=status id=update-status></span>
   </div>
  </div>
 </div><!-- /page-settings -->
</div><!-- /main -->

<!-- 新建标签弹窗 -->
<div class=modal-overlay id=create-tag-modal>
 <div class=modal-box>
  <h3 data-l data-zh="新建收藏标签" data-en="New Collection Tag">新建收藏标签</h3>
  <input id=new-tag-name placeholder="Tag name" data-l-ph data-zh="标签名" data-en="Tag name">
  <div class=modal-actions>
   <button class=crop-btn cancel onclick="closeCreateTagModal()" data-l data-zh="取消" data-en="Cancel">取消</button>
   <button class=crop-btn ok onclick="createTag()" data-l data-zh="创建" data-en="Create">创建</button>
  </div>
 </div>
</div>

<!-- 加入收藏夹弹窗 -->
<div class=modal-overlay id=fav-picker-modal>
 <div class=modal-box>
  <h3 data-l data-zh="加入收藏夹" data-en="Add to Favorites">加入收藏夹</h3>
  <div class=tag-picker id=fav-picker-tags></div>
  <div class=modal-actions style="margin-top:14px">
   <button class=crop-btn cancel onclick="closeFavPicker()" data-l data-zh="关闭" data-en="Close">关闭</button>
  </div>
 </div>
</div>

<script>
 // --- 侧边栏导航 ---
 let currentPage='search';
 function switchPage(page){
  if(currentPage===page)return;
  currentPage=page;
  document.querySelectorAll('.page-container').forEach(p=>p.classList.remove('active'));
  document.getElementById('page-'+page).classList.add('active');
  document.querySelectorAll('.sidebar-btn').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
  if(page==='favorites')loadFavTags();
  if(page==='settings')loadSettings();
 }
 // --- 顶部按钮栏 ---
 let MODE='pixiv';
 let DATASRC='__DATASRC__'; // 'user'|'demo'|'no-data'(服务端注入)
 function switchMode(m){
  if(MODE===m)return;
  switchModeNoGo(m);
  go();
 }
 // --- 更换横幅/头像(参考 pixiv 个人主页) ---
 const _fi=document.createElement('input');_fi.type='file';_fi.accept='image/png,image/jpeg,image/webp,image/gif';_fi.style.display='none';document.body.appendChild(_fi);
 function pick(kind){_fi.dataset.kind=kind;_fi.click();}
 _fi.addEventListener('change',()=>{
  const f=_fi.files[0];if(!f)return;
  if(f.size>15*1024*1024){alert(LANG==='zh'?'图片太大了,请选 15MB 以内的':'Image too large, pick under 15MB');return;}
  openCrop(_fi.dataset.kind,f); // 先框选,确认后才上传
  _fi.value='';
 });
 // --- 图片显示位置调整(拖动+滚轮缩放,参考 pixiv 传横幅) ---
 const POS={banner:{x:0,y:0,s:1},avatar:{x:0,y:0,s:1}};
 (async()=>{try{const r=await fetch('/api/asset-pos');const d=await r.json();
   if(d.banner)Object.assign(POS.banner,d.banner); if(d.avatar)Object.assign(POS.avatar,d.avatar);
   applyPos('banner');applyPos('avatar');}catch(e){}})();
 function applyPos(kind){const img=document.getElementById(kind+'-img');if(!img)return;
   const p=POS[kind];img.style.transform='translate('+p.x+'px,'+p.y+'px) scale('+p.s+')';}
 let adj=null;
 function enterAdj(kind){
  if(adj)return;
  const img=document.getElementById(kind+'-img');
  if(!img||img.style.display==='none'){alert(LANG==='zh'?'先上传图片,再调整显示位置':'Upload an image first');return;}
  adj={kind,img,px:POS[kind].x,py:POS[kind].y,ps:POS[kind].s,orig:{x:POS[kind].x,y:POS[kind].y,s:POS[kind].s}};
  img.classList.add('adj');
  document.getElementById('done-'+kind).style.display='flex';
  adj._down=e=>{if(e.button!==0)return;adj.drag={sx:e.clientX,sy:e.clientY,ox:adj.px,oy:adj.py};img.classList.add('drag');e.preventDefault();};
  adj._move=e=>{if(!adj.drag)return;adj.px=adj.drag.ox+(e.clientX-adj.drag.sx);adj.py=adj.drag.oy+(e.clientY-adj.drag.sy);
    img.style.transform='translate('+adj.px+'px,'+adj.py+'px) scale('+adj.ps+')';};
  adj._up=()=>{adj.drag=null;img.classList.remove('drag');};
  adj._wheel=e=>{e.preventDefault();const f=e.deltaY<0?1.1:0.9;adj.ps=Math.min(4,Math.max(0.3,adj.ps*f));
    img.style.transform='translate('+adj.px+'px,'+adj.py+'px) scale('+adj.ps+')';};
  adj._key=e=>{if(e.key==='Escape')cancelAdj();};
  img.addEventListener('mousedown',adj._down);
  document.addEventListener('mousemove',adj._move);
  document.addEventListener('mouseup',adj._up);
  img.addEventListener('wheel',adj._wheel,{passive:false});
  document.addEventListener('keydown',adj._key);
 }
 function doneAdj(kind){
  if(!adj)return;
  POS[kind].x=Math.round(adj.px);POS[kind].y=Math.round(adj.py);POS[kind].s=Math.round(adj.ps*100)/100;
  exitAdj();
  fetch('/api/asset-pos',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[kind]:POS[kind]})});
  const h=document.getElementById('hint');h.textContent=LANG==='zh'?'位置已保存 ✓':'Position saved ✓';setTimeout(()=>h.textContent='',1800);
 }
 function cancelAdj(){
  if(!adj)return;
  const p=adj.orig;POS[adj.kind].x=p.x;POS[adj.kind].y=p.y;POS[adj.kind].s=p.s;
  adj.img.style.transform='translate('+p.x+'px,'+p.y+'px) scale('+p.s+')';
  exitAdj();
 }
 function exitAdj(){
  if(!adj)return;
  adj.img.classList.remove('adj','drag');
  document.getElementById('done-'+adj.kind).style.display='none';
  adj.img.removeEventListener('mousedown',adj._down);
  document.removeEventListener('mousemove',adj._move);
  document.removeEventListener('mouseup',adj._up);
  adj.img.removeEventListener('wheel',adj._wheel);
  document.removeEventListener('keydown',adj._key);
  adj=null;
 }
 // --- 裁剪器:导入图片时框选范围(pixiv 式) ---
 const crop={kind:null,url:null,natW:0,natH:0,bw:0,bh:0,tx:0,ty:0,s:1,drag:null,fw:0,fh:0};
 function openCrop(kind,file){
  const url=URL.createObjectURL(file);
  const im=new Image();
  im.onload=()=>{
   crop.kind=kind;crop.url=url;crop.natW=im.naturalWidth;crop.natH=im.naturalHeight;
   document.getElementById('crop-modal').style.display='flex';
   const stage=document.getElementById('crop-stage'),ci=document.getElementById('crop-img');
   const stw=stage.clientWidth,sth=stage.clientHeight;
   const r=Math.min(stw/crop.natW,sth/crop.natH);
   crop.bw=crop.natW*r;crop.bh=crop.natH*r;crop.tx=0;crop.ty=0;crop.s=1;
   const ratio=kind==='banner'?Math.max(2.4,document.getElementById('banner').clientWidth/150):1;
   let fw,fh;
   if(ratio>=1){fw=Math.min(stw*0.94,sth*0.9*ratio);fh=fw/ratio;}
   else{fh=Math.min(sth*0.9,stw*0.94*ratio);fw=fh*ratio;}
   crop.fw=fw;crop.fh=fh;
   ci.src=url;ci.style.width=crop.bw+'px';ci.style.height=crop.bh+'px';
   const fr=document.getElementById('crop-frame');
   fr.style.width=fw+'px';fr.style.height=fh+'px';
   clampCrop();applyCrop();
   crop._down=e=>{if(e.button!==0)return;crop.drag={sx:e.clientX,sy:e.clientY,ox:crop.tx,oy:crop.ty};ci.classList.add('drag');e.preventDefault();};
   crop._move=e=>{if(!crop.drag)return;crop.tx=crop.drag.ox+(e.clientX-crop.drag.sx);crop.ty=crop.drag.oy+(e.clientY-crop.drag.sy);clampCrop();applyCrop();};
   crop._up=()=>{crop.drag=null;ci.classList.remove('drag');};
   crop._wheel=e=>{e.preventDefault();const f=e.deltaY<0?1.1:0.9;crop.s=Math.min(5,Math.max(0.3,crop.s*f));clampCrop();applyCrop();};
   crop._key=e=>{if(e.key==='Escape')cropCancel();};
   stage.addEventListener('mousedown',crop._down);
   document.addEventListener('mousemove',crop._move);
   document.addEventListener('mouseup',crop._up);
   stage.addEventListener('wheel',crop._wheel,{passive:false});
   document.addEventListener('keydown',crop._key);
  };
  im.src=url;
 }
 function clampCrop(){
  const bw=crop.bw*crop.s,bh=crop.bh*crop.s;
  const minTx=(crop.fw-bw)/2, maxTx=(bw-crop.fw)/2;
  const minTy=(crop.fh-bh)/2, maxTy=(bh-crop.fh)/2;
  if(maxTx>=minTx){crop.tx=Math.min(Math.max(crop.tx,minTx),maxTx);}
  else{crop.tx=(minTx+maxTx)/2;}
  if(maxTy>=minTy){crop.ty=Math.min(Math.max(crop.ty,minTy),maxTy);}
  else{crop.ty=(minTy+maxTy)/2;}
 }
 function applyCrop(){
  const ci=document.getElementById('crop-img');
  ci.style.transform='translate(calc(-50% + '+crop.tx+'px), calc(-50% + '+crop.ty+'px)) scale('+crop.s+')';
 }
 function cropCancel(){
  if(!crop.kind)return;
  const stage=document.getElementById('crop-stage'),ci=document.getElementById('crop-img');
  stage.removeEventListener('mousedown',crop._down);
  document.removeEventListener('mousemove',crop._move);
  document.removeEventListener('mouseup',crop._up);
  stage.removeEventListener('wheel',crop._wheel);
  document.removeEventListener('keydown',crop._key);
  document.getElementById('crop-modal').style.display='none';
  if(crop.url)URL.revokeObjectURL(crop.url);
  ci.removeAttribute('src');crop.kind=null;
 }
 function cropConfirm(){
  if(!crop.kind)return;
  const stw=document.getElementById('crop-stage').clientWidth,sth=document.getElementById('crop-stage').clientHeight;
  const imgW=crop.bw*crop.s,imgH=crop.bh*crop.s;
  const imgLeft=stw/2+crop.tx-imgW/2,imgTop=sth/2+crop.ty-imgH/2;
  const frLeft=(stw-crop.fw)/2,frTop=(sth-crop.fh)/2;
  const px=(frLeft-imgLeft)/imgW*crop.natW,py=(frTop-imgTop)/imgH*crop.natH;
  const pw=crop.fw/imgW*crop.natW,ph=crop.fh/imgH*crop.natH;
  const c=document.createElement('canvas');
  c.width=Math.max(2,Math.round(pw));c.height=Math.max(2,Math.round(ph));
  const ctx=c.getContext('2d');
  ctx.drawImage(document.getElementById('crop-img'),px,py,pw,ph,0,0,c.width,c.height);
  const kind=crop.kind;
  c.toBlob(async blob=>{
   try{
    const r=await fetch('/api/asset/'+kind,{method:'POST',headers:{'Content-Type':blob.type||'image/jpeg'},body:blob});
    const j=await r.json();
    if(j.ok){
     const img=document.getElementById(kind+'-img');
     img.style.display='';
     img.src='/assets/'+kind+'?t='+Date.now();
     const h=document.getElementById('hint');h.textContent=LANG==='zh'?'已裁剪并保存 ✓(可再点「调整位置」微调)':'Cropped & saved ✓';setTimeout(()=>h.textContent='',2500);
    }else{alert((LANG==='zh'?'上传失败: ':'Upload failed: ')+j.error);}
   }catch(e){alert((LANG==='zh'?'上传失败: ':'Upload failed: ')+e);}
  },'image/jpeg',0.92);
  cropCancel();
 }
 function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
// D) 关键词高亮: 把标题里命中的词用 <mark> 包起来
function hlText(s, words){
 if(!s||!words||!words.length)return esc(s);
 let out=esc(s);
 const list=[...(new Set(words.map(w=>String(w).toLowerCase()).filter(w=>w&&w.length>=2)))].sort((a,b)=>b.length-a.length);
 for(const w of list){
  const re=new RegExp(w.replace(/[.*+?^${}()|[\]\\\\]/g,'\\\\$&'),'gi');
  out=out.replace(re,m=>'<mark>'+m+'</mark>');
 }
 return out;
}
 function tagsOf(it){return (it.tags||[]).map(t=>typeof t==='object'?t.tag:(t||'')).filter(Boolean).slice(0,4).join(' · ');}
 // --- 自定义 Q 弹下拉 ---
 function setupDD(selId,textId,menuId,ddId){
  const sel=document.getElementById(selId), txt=document.getElementById(textId),
        menu=document.getElementById(menuId), dd=document.getElementById(ddId);
  const trigger=dd.querySelector('.dd-trigger');
  function render(){
   menu.innerHTML=[...sel.options].map(o=>`<div class="dd-opt${o.value===sel.value?' sel':''}" data-v="${esc(o.value)}">${esc(o.text)}</div>`).join('');
   txt.textContent=sel.options[sel.selectedIndex]?sel.options[sel.selectedIndex].text:'';
  }
  function open(){dd.classList.add('open');render();}
  function close(){dd.classList.remove('open');}
  trigger.addEventListener('click',e=>{e.stopPropagation();dd.classList.contains('open')?close():open();});
  trigger.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();dd.classList.contains('open')?close():open();}});
  menu.addEventListener('click',e=>{
   const opt=e.target.closest('.dd-opt'); if(!opt)return;
   sel.value=opt.dataset.v; close();
   sel.dispatchEvent(new Event('change')); // 触发 onchange=go()
  });
  document.addEventListener('click',e=>{ if(!dd.contains(e.target)) close(); });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape') close(); });
 }
 // 加载收藏标签下拉
 function loadColtags(){
  const r=document.getElementById('coltag');
  return fetch('/api/coltags').then(r=>r.json()).then(d=>{
   const lbl=LANG==='zh'?'全部收藏标签':'All coltags';
   r.innerHTML=`<option value="">${lbl}</option>`+d.tags.map(t=>`<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join('');
   syncDD();
  });
 }
 (async function(){ await loadColtags(); setupDD('coltag','coltag-text','coltag-menu','dd-coltag'); })();
 // 加载作品标签下拉
 function loadTags(){
  const r=document.getElementById('tag');
  return fetch('/api/tags').then(r=>r.json()).then(d=>{
   const lbl=LANG==='zh'?'全部作品标签(不限)':'All tags (any)';
   r.innerHTML=`<option value="">${lbl}</option>`+d.tags.map(t=>`<option value="${esc(t.tag)}">${esc(t.tag)} (${t.count})</option>`).join('');
   syncDD();
  });
 }
 (async function(){ await loadTags(); setupDD('tag','tag-text','tag-menu','dd-tag'); })();
// --- demo 模式(未导入收藏): 页面打开自动展示全部示例图 ---
(async function(){
 await Promise.all([
  (async()=>{await loadColtags();})(),
  (async()=>{await loadTags();})()
 ]);
 const _db=document.getElementById('demo-bar');
 const _it=document.getElementById('import-tip');
 if(DATASRC==='demo'){
  if(_db)_db.style.display='block';
  if(_it)_it.style.display='block';
  if(!location.hash){ go(); }
 }else if(_db){
  _db.style.display='none';
  if(_it && !localStorage.getItem('pfs_imported')){
   _it.style.display='block';
   setTimeout(()=>{ if(_it)_it.style.display='none'; }, 8000);
  }
 }
})();
 // 同步两个下拉的显示文本(undo/重放设置 select.value 后调用)
 function syncDD(){
  const c=document.getElementById('coltag');
  document.getElementById('coltag-text').textContent=c.options[c.selectedIndex]?c.options[c.selectedIndex].text:(LANG==='zh'?'全部收藏标签':'All coltags');
  const t=document.getElementById('tag');
  document.getElementById('tag-text').textContent=t.options[t.selectedIndex]?t.options[t.selectedIndex].text:(LANG==='zh'?'全部作品标签(不限)':'All tags (any)');
 }
 let undoStack=[]; // 每次搜索前保存一次状态,按 Ctrl+Z / Alt+← 可撤回
 function snapshot(){
  return {
   mode:MODE,
   q:document.getElementById('q').value,
   tag:document.getElementById('tag').value,
   colt:document.getElementById('coltag').value,
   html:document.getElementById('grid').innerHTML,
   meta:document.getElementById('meta').textContent,
   hint:document.getElementById('hint').textContent
  };
 }
 function restoreState(s){
  if(s.mode&&s.mode!==MODE)switchModeNoGo(s.mode);
  document.getElementById('q').value=s.q;
  document.getElementById('tag').value=s.tag;
  document.getElementById('coltag').value=s.colt;
  document.getElementById('grid').innerHTML=s.html;
  document.getElementById('meta').textContent=s.meta;
  document.getElementById('hint').textContent=s.hint||'';
  syncDD();
 }
function switchModeNoGo(m){
 if(MODE===m)return;
 MODE=m;
 document.getElementById('btn-pixiv').classList.toggle('active',m==='pixiv');
 document.getElementById('banner-mark-text').textContent='PixivFavSearch';
 document.getElementById('hd-title-text').textContent='PixivFavSearch';
 document.getElementById('hd-sub-text').textContent=LANG==='zh'?'本地 · 全部收藏 · 标题/标签/简介全字段搜索 · 假名→罗马音跨语言':'Local · All bookmarks · Full-text title/tag/desc · kana→romaji';
 document.getElementById('dd-coltag').style.display='';
 document.getElementById('dd-tag').style.display='';
 const bar=document.querySelector('.bar');
 if(bar) bar.style.display='';
 document.getElementById('q').placeholder=LANG==='zh'?'输入关键词，如: ibuki / 水着 / ブルアカ / Plana ...':'Search keyword, e.g. ibuki / swimsuit / Plana ...';
 }
 
// --- 从 pixiv 页面按「后退」键/鼠标侧键回来时:页面重载,按 URL 里的 #参数 自动恢复刚才的搜索结果 ---
(async function(){
 const h=(location.hash||'').replace(/^#/,''); if(!h)return;
 const p=new URLSearchParams(h);
 const q=(p.get('q')||'').trim(), tag=p.get('tag')||'', colt=p.get('colt')||'';
 const mode=p.get('mode')||'pixiv';
 if(!q&&!tag&&!colt&&mode==='pixiv')return;
 document.getElementById('q').value=q;
 // 等两个下拉框加载完再设值+重放搜索(否则选中的标签不生效)
 await new Promise(res=>{
  let n=0; const t=setInterval(()=>{
   const a=document.getElementById('coltag').options.length>1;
   const b=document.getElementById('tag').options.length>1;
   if((a&&b)||++n>60){clearInterval(t);res();}
  },50);
 });
 if(tag)document.getElementById('tag').value=tag;
 if(colt)document.getElementById('coltag').value=colt;
 syncDD();
 go();
})();

// --- 中/EN 切换 ---
let LANG='zh';
function langApply(){
 const zh=LANG==='zh';
 document.querySelectorAll('[data-l]').forEach(el=>{
  const t=el.getAttribute(zh?'data-zh':'data-en');
  if(t!=null) el.textContent=t;
 });
 const q=document.getElementById('q');
 const ph=q.getAttribute(zh?'data-zh':'data-en');
 if(ph!=null) q.placeholder=ph;
 document.querySelectorAll('[data-l-t]').forEach(el=>{
  const t=el.getAttribute(zh?'data-zh-t':'data-en-t');
  if(t!=null) el.title=t;
 });
 // 刷新两个下拉的语言文案
 loadColtags(); loadTags();
 // demo 模式: 已渲染的占位卡片文字与缩略图 ?lang= 跟随语言切换
 if(DATASRC==='demo'){
  const zh=LANG==='zh';
  document.querySelectorAll('#grid .card').forEach(c=>{
   const tt=c.querySelector('.tt'); if(tt) tt.textContent=zh?'标题':'Title';
   const au=c.querySelector('.au'); if(au) au.textContent=zh?'作者':'Author';
   const tg=c.querySelector('.tg'); if(tg) tg.textContent='🏷 '+(zh?'示例标签':'Sample tag');
   const im=c.querySelector('img'); if(im&&im.src.indexOf('/thumb/')>=0){
    const base=im.src.split('/thumb/')[1].split('?')[0];
    im.src='/thumb/'+base+'?lang='+LANG;
   }
  });
 }
}
function toggleLang(){ LANG=LANG==='zh'?'en':'zh'; langApply(); }
// --- 更新检查提示 ---
(async function(){
 try{
  const r=await fetch('/api/version');
  const d=await r.json();
  if(d.update){
   const el=document.createElement('div');
   el.style.cssText='position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:99;background:linear-gradient(135deg,#ef9eff,#c77dff);color:#2b0030;font-size:13px;font-weight:700;padding:10px 18px;border-radius:24px;box-shadow:0 6px 20px rgba(0,0,0,.4);cursor:pointer';
   el.textContent=LANG==='zh'?'✨ 新版本 v'+d.latest+' 可用, 点击前往下载':'✨ v'+d.latest+' available, click to download';
   el.onclick=()=>location.href=d.url||'https://github.com/Hzm66647/PixivFavSearch/releases/latest';
   document.body.appendChild(el);
  }
}catch(e){}
})();

// === 核心搜索(开源版修复: 补回丢失的 go/undo) ===
let _hs=0;
function markHistory(){ history.pushState({hs:++_hs},'',location.pathname); }
function undoSearch(){
 if(!undoStack.length)return;
 const s=undoStack.pop();
 restoreState(s);
 markHistory();
}
async function go(){
 const q=document.getElementById('q').value.trim();
 const tag=document.getElementById('tag').value;
 const colt=document.getElementById('coltag').value;
 const g=document.getElementById('grid');const m=document.getElementById('meta');
 const cur=snapshot();
 const top=undoStack[undoStack.length-1];
 if(!top||top.q!==cur.q||top.tag!==cur.tag||top.colt!==cur.colt||top.mode!==cur.mode){
  undoStack.push(cur);if(undoStack.length>50)undoStack.shift();
  markHistory();
 }
 g.innerHTML='<div class=empty>搜索中…</div>';
 const r=await fetch('/api/search?mode='+MODE+'&q='+encodeURIComponent(q)+'&tag='+encodeURIComponent(tag)+'&coltag='+encodeURIComponent(colt));
 const d=await r.json();
 m.textContent=(LANG==='zh'
 ?(colt?'收藏标签「'+esc(colt)+'」内 · ':'')+(tag?'作品标签「'+esc(tag)+'」内 · ':'')+'共 '+d.total+' 幅作品命中(标题+标签+说明文字)'+(d.total>200?'，显示前200':'')
 :(colt?'In coltag "'+esc(colt)+'" · ':'')+(tag?'In tag "'+esc(tag)+'" · ':'')+d.total+' works'+(d.total>200?' · showing first 200':''));
 if(!d.items.length){g.innerHTML='<div class=empty>'+(LANG==='zh'?'没有匹配的作品':'No matching works')+'</div>';return;}
 g.innerHTML=d.items.map(it=>{
  if(DATASRC==='demo'){
   return `<div class=card>
   <img loading=lazy decoding=async src="/thumb/${it.id}?lang=${LANG}" onerror="this.onerror=null;this.style.visibility='hidden'">
   <div class=tt>${LANG==='zh'?'标题':'Title'}</div>
   <div class=au>${LANG==='zh'?'作者':'Author'}</div>
   <div class=tg>🏷 ${LANG==='zh'?'示例标签':'Sample tag'}</div>
  </div>`;
  }
  return `<div class=card>
   <a href="https://www.pixiv.net/artworks/${it.id}">
     <img loading=lazy decoding=async src="/thumb/${it.id}" onerror="this.onerror=null;this.style.visibility='hidden'">
     <div class=tt>${hlText(it.title, it.hl)}</div>
     <div class=au>${esc(it.userName)}</div>
   </a>
   <div class=tg>🏷 ${esc(tagsOf(it))}</div>
   <button class="fav-btn" data-work-id="${it.id}" onclick="event.stopPropagation();openFavPicker('${it.id}')">${LANG==='zh'?'⭐ 加入收藏夹':'⭐ Add to Fav'}</button>
   <a class=go href="https://www.pixiv.net/artworks/${it.id}">🔗 ${LANG==='zh'?'打开 Pixiv':'Open Pixiv'}</a>
 </div>`;
 }).join('');
 history.replaceState(history.state,'','#'+new URLSearchParams({mode:MODE,q:q,tag:tag,colt:colt}).toString());
 updateFavBtnStates();
}
// Ctrl+Z 撤销(捕获阶段,拦截输入框原生撤销)
document.addEventListener('keydown',function(e){
 if((e.ctrlKey||e.metaKey)&&(e.key==='z'||e.key==='Z')){e.preventDefault();e.stopPropagation();undoSearch();}
},true);
// 导入/更新收藏(CDP 抓取最新收藏)
async function doImport(){
 const btn=document.getElementById('btn-import');
 const hint=document.getElementById('hint');
 if(btn.classList.contains('loading'))return;
 btn.classList.add('loading');btn.textContent=LANG==='zh'?'⏳ 导入中…':'⏳ Importing…';
 hint.textContent=LANG==='zh'?'正在连接浏览器抓取最新收藏, 请稍候…':'Connecting to browser to fetch latest bookmarks…';
 try{
  const r=await fetch('/api/import',{method:'POST'});
  const j=await r.json();
  if(!j.started){ hint.textContent=LANG==='zh'?'已有导入任务在运行, 请稍候…':'Import already running…'; btn.classList.remove('loading');btn.textContent=(LANG==='zh'?'📥 导入/更新收藏':'📥 Import / Update'); return; }
  for(let i=0;i<90;i++){
   await new Promise(res=>setTimeout(res,2000));
   const sr=await fetch('/api/import-status');
   const s=await sr.json();
   if(!s.running){
    hint.style.color=s.code===0?'#34C759':'#FF453A';
    hint.textContent=s.msg||(LANG==='zh'?'导入完成':'Done');
    btn.classList.remove('loading');btn.textContent=(LANG==='zh'?'📥 导入/更新收藏':'📥 Import / Update');
    if(s.code===0){ localStorage.setItem('pfs_imported','1'); await go(); }
    setTimeout(()=>{hint.style.color='';},6000);
    return;
   }
  }
  hint.textContent=LANG==='zh'?'导入超时, 请检查浏览器调试端口是否开启':'Import timeout, check browser debug port';
 }catch(e){
  hint.style.color='#FF453A';hint.textContent=(LANG==='zh'?'导入请求失败: ':'Import request failed: ')+e.message;
  setTimeout(()=>{hint.style.color='';},6000);
 }
 btn.classList.remove('loading');btn.textContent=(LANG==='zh'?'📥 导入/更新收藏':'📥 Import / Update');
}
// Alt+← / 鼠标后退 → popstate 恢复上一步搜索
window.addEventListener('popstate',function(){
 if(undoStack.length){
  const s=undoStack.pop();
  restoreState(s);
  markHistory();
 }
});

// ============================================================
// 收藏夹页逻辑
// ============================================================
let favTags=[]; // [{tag, count}]
let currentFavTag=null;

async function loadFavTags(){
 try{
  const r=await fetch('/api/coltags');
  const d=await r.json();
  favTags=d.tags||[];
  renderFavGrid();
 }catch(e){}
}

function renderFavGrid(){
 const grid=document.getElementById('fav-grid');
 if(!favTags.length){
  grid.innerHTML='<div class=empty data-l data-zh="还没有收藏标签，点击上方「新建标签」创建" data-en="No tags yet, click New Tag above">还没有收藏标签，点击上方「新建标签」创建</div>';
  return;
 }
 grid.innerHTML=favTags.map(t=>`<div class=fav-card onclick="openFavTag('${esc(t.tag)}')">
  <button class=del-btn onclick="event.stopPropagation();deleteTag('${esc(t.tag)}')" title="删除">✕</button>
  <div class=tag-name>${esc(t.tag)}</div>
  <div class=tag-count>${t.count} ${LANG==='zh'?'幅作品':'works'}</div>
 </div>`).join('');
}

async function openFavTag(tag){
 currentFavTag=tag;
 document.getElementById('fav-list-header').style.display='none';
 document.getElementById('fav-detail-header').style.display='flex';
 document.getElementById('fav-detail-title').textContent=tag;
 document.getElementById('fav-grid').style.display='none';
 document.getElementById('fav-works').style.display='block';
 try{
  const r=await fetch('/api/coltags/'+encodeURIComponent(tag)+'/works');
  const d=await r.json();
  const grid=document.getElementById('fav-works-grid');
  if(!d.items||!d.items.length){
   grid.innerHTML='<div class=empty data-l data-zh="该标签下暂无作品" data-en="No works in this tag">该标签下暂无作品</div>';
   return;
  }
  grid.innerHTML=d.items.map(it=>`<div class=card>
   <a href="https://www.pixiv.net/artworks/${it.id}">
     <img loading=lazy decoding=async src="/thumb/${it.id}" onerror="this.onerror=null;this.style.visibility='hidden'">
     <div class=tt>${hlText(it.title, it.hl)}</div>
     <div class=au>${esc(it.userName)}</div>
   </a>
   <div class=tg>🏷 ${esc(tagsOf(it))}</div>
   <button class="fav-btn in-fav" data-work-id="${it.id}" onclick="event.stopPropagation();toggleFavTag('${it.id}','${esc(tag)}')">${LANG==='zh'?'✓ 已收藏':'✓ In Fav'}</button>
   <a class=go href="https://www.pixiv.net/artworks/${it.id}">🔗 ${LANG==='zh'?'打开 Pixiv':'Open Pixiv'}</a>
  </div>`).join('');
 }catch(e){}
}

function showFavList(){
 currentFavTag=null;
 document.getElementById('fav-list-header').style.display='flex';
 document.getElementById('fav-detail-header').style.display='none';
 document.getElementById('fav-grid').style.display='grid';
 document.getElementById('fav-works').style.display='none';
 loadFavTags();
}

async function deleteTag(tag){
 if(!confirm((LANG==='zh'?'确定删除标签「':'Delete tag "')+tag+(LANG==='zh'?'」？?':'"?')))return;
 try{
  const r=await fetch('/api/coltags/'+encodeURIComponent(tag),{method:'DELETE'});
  const d=await r.json();
  if(d.ok){ loadFavTags(); }
  else{ alert(d.error||(LANG==='zh'?'删除失败':'Delete failed')); }
 }catch(e){ alert(LANG==='zh'?'删除失败':'Delete failed'); }
}

function showCreateTagModal(){
 document.getElementById('create-tag-modal').classList.add('show');
 document.getElementById('new-tag-name').value='';
 document.getElementById('new-tag-name').focus();
}
function closeCreateTagModal(){
 document.getElementById('create-tag-modal').classList.remove('show');
}
async function createTag(){
 const name=document.getElementById('new-tag-name').value.trim();
 if(!name)return;
 try{
  const r=await fetch('/api/coltags',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
  const d=await r.json();
  if(d.ok){ closeCreateTagModal(); loadFavTags(); }
  else{ alert(d.error||(LANG==='zh'?'创建失败':'Create failed')); }
 }catch(e){ alert(LANG==='zh'?'创建失败':'Create failed'); }
}

// 加入收藏夹弹窗
let favPickerWorkId=null;
async function openFavPicker(workId){
 favPickerWorkId=workId;
 if(!favTags.length){ alert(LANG==='zh'?'请先创建收藏标签':'Create a tag first'); return; }
 renderFavPickerTags();
 document.getElementById('fav-picker-modal').classList.add('show');
}
function closeFavPicker(){
 document.getElementById('fav-picker-modal').classList.remove('show');
 favPickerWorkId=null;
}
function renderFavPickerTags(){
 const picker=document.getElementById('fav-picker-tags');
 picker.innerHTML=favTags.map(t=>`<span class=tag-chip data-tag="${esc(t.tag)}" onclick="toggleFavTag(favPickerWorkId,'${esc(t.tag)}')">${esc(t.tag)} (${t.count})</span>`).join('');
 updateFavPickerStates();
}
async function toggleFavTag(workId,tag){
 try{
  const r=await fetch('/api/coltags/'+encodeURIComponent(tag)+'/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_id:workId})});
  const d=await r.json();
  if(d.ok){
   // 更新本地 favTags 数量
   const ft=favTags.find(f=>f.tag===tag);
   if(ft)ft.count=d.count;
   renderFavPickerTags();
   // 如果当前在收藏夹详情页，刷新
   if(currentFavTag===tag){ openFavTag(tag); }
   // 如果当前在搜索页，更新按钮状态
   if(currentPage==='search')updateFavBtnState(workId);
  }
 }catch(e){}
}
function updateFavBtnStates(){
 if(!favTags.length)return;
 document.querySelectorAll('.fav-btn[data-work-id]').forEach(btn=>{
  const wid=btn.dataset.workId;
  updateFavBtnState(wid);
 });
}
function updateFavBtnState(workId){
 const inAny=favTags.some(t=>t._workIds&&t._workIds.has(workId));
 const btn=document.querySelector('.fav-btn[data-work-id="'+workId+'"]');
 if(!btn)return;
 if(inAny){ btn.classList.add('in-fav'); btn.textContent=LANG==='zh'?'✓ 已收藏':'✓ In Fav'; }
 else{ btn.classList.remove('in-fav'); btn.textContent=LANG==='zh'?'⭐ 加入收藏夹':'⭐ Add to Fav'; }
}
function updateFavPickerTags(){
 // 异步加载每个标签的作品id,用于判断按钮状态(仅在弹窗打开时调用)
 if(!favTags.length)return;
 favTags.forEach(async t=>{
  try{
   const r=await fetch('/api/coltags/'+encodeURIComponent(t.tag)+'/works');
   const d=await r.json();
   t._workIds=new Set(d.items.map(i=>i.id));
  }catch(e){}
 });
}

// ============================================================
// 设置页逻辑
// ============================================================
async function loadSettings(){
 // 加载代理配置
 try{
  const r=await fetch('/api/settings');
  const d=await r.json();
  document.getElementById('proxy-input').value=d.proxy||'';
 }catch(e){}
 // 加载 cookie 状态
 try{
  const r=await fetch('/api/first-run/status');
  const d=await r.json();
  const el=document.getElementById('cookie-status');
  if(d.cookies_exist){
   el.textContent=(LANG==='zh'?'已登录 uid=':'Logged in uid=')+d.uid+(LANG==='zh'?' , ':' , ')+d.cookie_count+(LANG==='zh'?' 个 cookie':' cookies');
  }else{
   el.textContent=LANG==='zh'?'未登录':'Not logged in';
  }
 }catch(e){}
 // 加载数据状态
 try{
  const r=await fetch('/api/tags');
  const d=await r.json();
  document.getElementById('data-status').textContent=(LANG==='zh'?'共 ':'')+d.total+(LANG==='zh'?' 个作品标签':' work tags');
 }catch(e){}
 // 关于
 try{
  const r=await fetch('/api/about');
  const d=await r.json();
  document.getElementById('about-version').textContent=d.version;
  document.getElementById('about-link').href=d.github||'https://github.com/Hzm66647/PixivFavSearch';
 }catch(e){}
}

async function saveProxy(){
 const proxy=document.getElementById('proxy-input').value.trim();
 const status=document.getElementById('proxy-status');
 try{
  const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proxy})});
  const d=await r.json();
  if(d.ok){ status.textContent='✓ '+(LANG==='zh'?'已保存':'Saved'); status.className='status'; }
  else{ status.textContent='✗ '+(d.error||(LANG==='zh'?'保存失败':'Failed')); status.className='status error'; }
 }catch(e){ status.textContent='✗ Error'; status.className='status error'; }
 setTimeout(()=>{status.textContent='';},3000);
}

async function clearCookies(){
 if(!confirm(LANG==='zh'?'确定清除 cookie 吗？清除后需要重新登录。':'Clear cookies? You will need to re-login.'))return;
 try{
  const r=await fetch('/api/settings/clear-cookies',{method:'POST'});
  const d=await r.json();
  if(d.ok){ alert(LANG==='zh'?'Cookie 已清除':'Cookies cleared'); loadSettings(); }
  else{ alert(d.error||(LANG==='zh'?'清除失败':'Failed')); }
 }catch(e){ alert(LANG==='zh'?'请求失败':'Request failed'); }
}

async function clearAllData(){
 if(!confirm(LANG==='zh'?'确定清空所有收藏数据吗？此操作不可恢复！':'Clear all bookmark data? This cannot be undone!'))return;
 try{
  const r=await fetch('/api/settings/clear-data',{method:'POST'});
  const d=await r.json();
  if(d.ok){ alert(LANG==='zh'?'数据已清空':'Data cleared'); loadSettings(); }
  else{ alert(d.error||(LANG==='zh'?'操作失败':'Failed')); }
 }catch(e){ alert(LANG==='zh'?'请求失败':'Request failed'); }
}

async function checkUpdate(){
 const status=document.getElementById('update-status');
 status.textContent=LANG==='zh'?'检查中...':'Checking...';
 try{
  const r=await fetch('/api/about');
  const d=await r.json();
  if(d.update){
   status.textContent='✨ v'+d.latest+(LANG==='zh'?' 可用!':' available!');
   if(confirm((LANG==='zh'?'新版本 v'+d.latest+' 可用，是否前往下载？':'v'+d.latest+' available, open download page?'))){
    window.open(d.url||'https://github.com/Hzm66647/PixivFavSearch/releases/latest','_blank');
   }
  }else{
   status.textContent=LANG==='zh'?'已是最新版本 ✓':'Up to date ✓';
  }
 }catch(e){ status.textContent='✗ Error'; }
 setTimeout(()=>{status.textContent='';},5000);
}
</script>
'''

content = content[:start_idx] + new_index + content[end_idx:]

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Done! Replaced INDEX HTML ({len(new_index)} chars)")