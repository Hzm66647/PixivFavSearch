# -*- mode: python ; coding: utf-8 -*-
"""PixivFavSearch 桌面版打包配置 (重建版)

入口: desktop_app.py (pywebview 窗口 + pystray 托盘 + 单实例锁)
要点 (README「编译要点」):
  - console=False  GUI 应用无黑窗
  - pykakasi 的 .db 字典数据必须显式收集, 否则 exe 启动即崩 (MEI 临时目录找不到)
  - freeze_support 已在 desktop_app.py 处理 (onefile 多进程 GUI 必需)
  - icon.ico 作为程序图标
"""
import glob, os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# --- pykakasi 字典数据 (必需, 别删) ---
datas = []
try:
    import pykakasi
    _pk = os.path.dirname(pykakasi.__file__)
    for _f in glob.glob(os.path.join(_pk, "data", "*.db")):
        datas.append((_f, "pykakasi/data"))
except Exception:
    pass

# --- 首次运行回退用示例数据 (全新机器无收藏时展示, 别删) ---
_spdir = globals().get("SPECPATH") or os.path.dirname(os.path.abspath(globals().get("SPEC", ".")))
_demo = os.path.join(_spdir, "data", "demo_data.json")
if os.path.exists(_demo):
    datas.append((_demo, "."))
else:
    print(f"[SPEC-WARN] 未找到示例数据: {_demo}")

# --- jieba / opencc / pypinyin 数据 ---
for _mod in ("jieba", "opencc", "pypinyin"):
    try:
        datas += collect_data_files(_mod)
    except Exception:
        pass

# --- pywebview / pystray 平台后端子模块 ---
hiddenimports = []
for _m in ("webview", "pystray"):
    try:
        hiddenimports += collect_submodules(_m)
    except Exception:
        pass
hiddenimports += [
    "webview.platforms.edgechromium", "webview.platforms.winforms",
    "clr", "pythonnet",
    "pystray._win32",
    "pykakasi", "jieba", "opencc", "pypinyin", "socks",
]

a = Analysis(
    ['desktop_app.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PixivFavSearch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
