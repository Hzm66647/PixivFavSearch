"""PixivFavSearch - 本地书签搜索工具
启动后浏览器打开 http://127.0.0.1:8897/
输入标题关键词 -> 列出匹配作品(标题/作者/链接/缩略图)
缩略图按需下载并缓存到 data/thumbs/
"""
VERSION = "1.0.0"
import os, sys, re, json, time, threading, urllib.request, urllib.parse, subprocess, socks as pysocks, socket as pysocket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ⚠️ 无窗口启动: venv 的 pythonw.exe 实际会转调 uv python.exe(控制台程序),
# 会闪现 conhost 黑窗口。启动时立刻隐藏自己的控制台窗口。
try:
    import ctypes
    _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _hwnd:
        ctypes.windll.user32.ShowWindow(_hwnd, 0)  # SW_HIDE
except Exception:
    pass

# ⚠️ 真 pythonw (GUI 无控制台) 下 stdout/stderr 是 None, print() 会崩。
# 重定向到日志文件, 保证 print 不炸。
try:
    if sys.stdout is None:
        sys.stdout = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pix_server_stdout.log"), "a", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = sys.stdout
except Exception:
    pass

# 数据目录: %LOCALAPPDATA%\PixivFavSearch (桌面应用标准位置, 随用户走)
APP_DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "PixivFavSearch")
OUT = os.path.join(APP_DATA, "data")
DATA = os.path.join(OUT, "bookmarks.json")
DEMO_DATA = os.path.join(OUT, "demo_data.json")
THUMB = os.path.join(OUT, "thumbs")
COLTAGS = os.path.join(OUT, "coltags.json")
os.makedirs(THUMB, exist_ok=True)
# onefile 打包: exe 内自带一份示例数据作为首次运行回退(在 _MEIPASS 临时解压目录)
_MEIPASS = getattr(sys, "_MEIPASS", None)
if _MEIPASS and not os.path.exists(DEMO_DATA):
    _bundle_demo = os.path.join(_MEIPASS, "demo_data.json")
    if os.path.exists(_bundle_demo):
        try:
            with open(_bundle_demo, encoding="utf-8") as _f:
                _demo_src_text = _f.read()
            with open(DEMO_DATA, "w", encoding="utf-8", newline="\n") as _f:
                _f.write(_demo_src_text)
        except Exception:
            pass
ASSETS = os.path.join(APP_DATA, "pix_assets")
os.makedirs(ASSETS, exist_ok=True)
POS_FILE = os.path.join(ASSETS, "pos.json")
PORT = int(os.environ.get("PIX_PORT", "8897"))

# --- 日志系统: %LOCALAPPDATA%\PixivFavSearch\log\YYYY-MM.txt (DEBUG 精度, 中英双语) ---
import datetime as _dt
LOG_DIR = os.path.join(APP_DATA, "log")
os.makedirs(LOG_DIR, exist_ok=True)
_LOG_LOCK = threading.Lock()

def _log_path():
    """返回当前年月对应的日志文件路径。按年-月建文件, 如 2026-08.txt"""
    _now = _dt.datetime.now()
    return os.path.join(LOG_DIR, f"{_now.year}-{_now.month:02d}.txt")

def _write_log(level, zh, en=""):
    """写入日志文件。年月轮转: 跨月自动建新文件。"""
    try:
        _now = _dt.datetime.now()
        _ts = _now.strftime("%Y-%m-%d %H:%M:%S")
        _en_part = f" | {en}" if en else ""
        _line = f"[{_ts}] [{level}] {zh}{_en_part}\n"
        with _LOG_LOCK:
            with open(_log_path(), "a", encoding="utf-8") as _f:
                _f.write(_line)
    except Exception:
        pass  # 日志本身不能崩

def log_debug(zh, en=""): _write_log("DEBUG", zh, en)
def log_info(zh, en=""):  _write_log("INFO",  zh, en)
def log_warn(zh, en=""):  _write_log("WARN",  zh, en)
def log_error(zh, en=""): _write_log("ERROR", zh, en)

# 日志函数别名(供 desktop_app 等外部模块导入用)
__all__ = [x for x in dir() if x.startswith("log_")]

# ===== 插件系统: 可插拔数据源管理 =====
import hashlib as _hashlib

# 插件配置文件: %APPDATA%\PixivFavSearch\plugins.json
PLUGIN_CONFIG_FILE = os.path.join(APP_DATA, "plugins.json")

# 插件数据存储: {plugin_id: [items]}
PLUGIN_DATA = {}
PLUGIN_LIST = []  # 有序列表,保持UI顺序
PLUGINS_DIR = os.path.join(APP_DATA, "plugins")  # 插件文件夹（用户拖拽 .plug 文件到这里即可安装）
MARKET_URL_DEFAULT = "https://raw.githubusercontent.com/Hzm66647/PixivFavSearch/refs/heads/plugin-market/market.json"

# 标准字段定义
PLUGIN_STD_FIELDS = ["id", "title", "author", "thumb", "tags", "url", "desc"]

# 字段自动探测规则: {标准字段: [(匹配模式, 置信度), ...]}
_FIELD_RULES = {
    "id":    [("id", 95), ("uid", 85), ("pid", 80), ("no", 60), ("编号", 90)],
    "title": [("title", 95), ("name", 90), ("标题", 95), ("名前", 90), ("题名", 85)],
    "author":[("author", 90), ("artist", 90), ("user", 75), ("author_name", 95),
              ("作者", 95), ("画师", 95), ("アーティスト", 90)],
    "thumb": [("thumb", 90), ("image", 85), ("cover", 85), ("img", 80), ("thumbnail", 90),
              ("图片", 85), ("封面", 90), ("画像", 85)],
    "tags":  [("tags", 95), ("tag", 85), ("label", 80), ("标签", 95), ("タグ", 90)],
    "url":   [("url", 90), ("link", 85), ("href", 80), ("链接", 90), ("URL", 90)],
    "desc":  [("desc", 85), ("description", 90), ("summary", 85), ("alt", 70),
              ("描述", 90), ("说明", 85), ("説明", 85)],
}

def _probe_field_type(values):
    """采样字段值,返回类型特征"""
    if not values:
        return "empty"
    sample = values[:20]
    types = set()
    for v in sample:
        if isinstance(v, list):
            types.add("list")
        elif isinstance(v, str):
            if v.startswith("http"):
                types.add("url")
            else:
                types.add("str")
        elif isinstance(v, (int, float)):
            types.add("num")
        elif isinstance(v, dict):
            types.add("dict")
    return types

def _detect_fields(sample_items):
    """自动探测JSON字段映射。返回 {标准字段: (源字段, 置信度)}"""
    if not sample_items:
        return {}
    
    # 收集所有字段及其值
    all_fields = {}
    for item in sample_items:
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if k.startswith("_"):
                continue
            all_fields.setdefault(k, []).append(v)
    
    result = {}
    used_source_fields = set()
    
    # 按优先级匹配每个标准字段
    for std_field in PLUGIN_STD_FIELDS:
        rules = _FIELD_RULES.get(std_field, [])
        candidates = []
        
        for src_field, values in all_fields.items():
            if src_field in used_source_fields:
                continue
            
            src_lower = src_field.lower()
            best_score = 0
            
            # 规则匹配
            for pattern, score in rules:
                if pattern == src_lower:
                    best_score = max(best_score, score)
                elif pattern in src_lower and len(pattern) >= 3:
                    best_score = max(best_score, score - 10)
            
            # 值类型辅助判断
            if best_score > 0:
                types = _probe_field_type(values)
                if std_field == "thumb" and "url" in types:
                    best_score += 5
                elif std_field == "tags" and "list" in types:
                    best_score += 5
                elif std_field == "id" and "num" in types:
                    best_score += 3
                candidates.append((src_field, best_score))
        
        if candidates:
            candidates.sort(key=lambda x: -x[1])
            best = candidates[0]
            if best[1] >= 60:
                result[std_field] = (best[0], best[1])
                used_source_fields.add(best[0])
    
    return result

def _normalize_item(raw_item, mapping, plugin_id):
    """把原始数据项按mapping转成标准格式"""
    if not isinstance(raw_item, dict):
        return None
    
    def _extract_thumb(val):
        """从各种格式提取URL"""
        if isinstance(val, str):
            return val if val.startswith("http") else None
        if isinstance(val, dict):
            for k in ("url", "src", "href", "large", "original"):
                if isinstance(val.get(k), str) and val[k].startswith("http"):
                    return val[k]
        if isinstance(val, list) and val:
            return _extract_thumb(val[0])
        return None
    
    def _extract_tags(val):
        """统一标签格式为字符串列表"""
        if isinstance(val, list):
            result = []
            for t in val:
                if isinstance(t, dict):
                    tag = t.get("tag") or t.get("name") or t.get("label")
                    if tag:
                        result.append(str(tag))
                elif isinstance(t, str):
                    result.append(t)
            return result
        if isinstance(val, str):
            return [t.strip() for t in val.replace(",", " ").split() if t.strip()]
        return []
    
    def _extract_author(val):
        """提取作者名字"""
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            return val.get("name") or val.get("user") or val.get("author") or ""
        return str(val) if val else ""
    
    raw_id = raw_item.get(mapping.get("id", "id")) or ""
    title = raw_item.get(mapping.get("title", "title")) or ""
    
    if not raw_id and not title:
        return None
    
    item = {
        "id": str(raw_id),
        "title": str(title),
        "author": _extract_author(raw_item.get(mapping.get("author", "author"), "")),
        "thumb": _extract_thumb(raw_item.get(mapping.get("thumb", "thumb"), "")) or "",
        "tags": _extract_tags(raw_item.get(mapping.get("tags", "tags"), [])),
        "url": (raw_item.get(mapping.get("url", "url")) or "") if isinstance(raw_item.get(mapping.get("url", "url"), ""), str) else "",
        "desc": str(raw_item.get(mapping.get("desc", "desc"), "")),
        "source": plugin_id,
    }
    
    return item

def _build_plugin_index(items):
    """为插件数据构建搜索索引"""
    for it in items:
        title = it.get("title") or ""
        tags = " ".join(it.get("tags", []))
        desc = it.get("desc", "")
        author = it.get("author", "")
        raw = " ".join(x for x in (title, tags, desc, author) if x)
        it.setdefault("_title_rom", romanize(title).lower())
        it.setdefault("_search", raw.lower())
        it.setdefault("_search_rom", romanize(raw).lower())
        it.setdefault("_norm", _norm_cjk(raw).lower())
        it.setdefault("_norm_title", _norm_cjk(title).lower())
        it.setdefault("_search_py", _pinyin(raw).lower())
        it.setdefault("_title_py", _pinyin(title).lower())

def _load_plugin(plugin):
    """加载单个插件的数据"""
    pid = plugin["id"]
    mapping = plugin.get("mapping", {})
    config = plugin.get("config", {})
    
    try:
        if plugin["type"] == "custom" and config.get("url"):
            # 自定义URL数据源
            url = config["url"]
            req = urllib.request.Request(url, headers={"User-Agent": "PixivFavSearch/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            if not isinstance(data, list):
                if isinstance(data, dict):
                    # 尝试找数组字段
                    for k, v in data.items():
                        if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                            data = v
                            break
                    else:
                        return {"error": "数据格式不是列表,也无法找到数组字段"}
                else:
                    return {"error": "数据格式不是列表"}
        else:
            # 内置数据源: 从本地JSON加载
            data_file = config.get("data_file", "")
            if not data_file:
                return {"error": "未配置文件路径"}
            
            # 支持相对路径(相对于OUT目录)和绝对路径
            if os.path.isabs(data_file):
                fpath = data_file
            else:
                fpath = os.path.join(OUT, data_file)
            
            if not os.path.exists(fpath):
                return {"error": f"文件不存在: {os.path.basename(fpath)}"}
            
            # 支持 plugins 目录下的相对路径
            if not os.path.isabs(fpath) and not os.path.exists(fpath):
                alt = os.path.join(PLUGINS_DIR, plugin.get("id", ""), "data.json")
                if os.path.exists(alt):
                    fpath = alt
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        
        if not isinstance(data, list):
            return {"error": "数据不是列表格式"}
        
        # 标准化
        items = []
        for raw in data:
            item = _normalize_item(raw, mapping, pid)
            if item:
                items.append(item)
        
        if not items:
            return {"error": "没有有效数据条目"}
        
        _build_plugin_index(items)
        
        PLUGIN_DATA[pid] = items
        return {"ok": True, "count": len(items)}
    
    except Exception as e:
        return {"error": repr(e)[:200]}


def _get_plugin_dir(pid):
    """获取插件数据目录"""
    return os.path.join(PLUGINS_DIR, pid)

def scan_plugins_dir():
    """扫描 plugins 文件夹，自动安装新的 .plug 文件"""
    if not os.path.isdir(PLUGINS_DIR):
        return
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    for fname in os.listdir(PLUGINS_DIR):
        if not fname.endswith('.plug'):
            continue
        fpath = os.path.join(PLUGINS_DIR, fname)
        try:
            _install_plugin_from_zip(fpath)
        except Exception as e:
            print(f"[plugin] 扫描安装失败 {fname}: {repr(e)[:100]}")

def _install_plugin_from_zip(filepath):
    """从 .zip/.plug 文件安装插件"""
    import zipfile, shutil
    pid_base = os.path.splitext(os.path.basename(filepath))[0]
    extract_dir = os.path.join(PLUGINS_DIR, f"_{pid_base}_tmp")
    try:
        # 解压
        with zipfile.ZipFile(filepath, 'r') as z:
            z.extractall(extract_dir)
        # 读取 manifest
        manifest_path = os.path.join(extract_dir, 'manifest.json')
        if not os.path.exists(manifest_path):
            # 没有 manifest，自动生成
            manifest = {
                "id": pid_base,
                "name": pid_base,
                "version": "1.0.0",
                "icon": "📦",
                "description": f"本地安装: {pid_base}",
                "type": "custom"
            }
        else:
            with open(manifest_path, encoding='utf-8') as f:
                manifest = json.load(f)
        pid = manifest.get('id', pid_base)
        # 检查是否已存在
        final_dir = _get_plugin_dir(pid)
        if os.path.exists(final_dir):
            shutil.rmtree(final_dir)
        os.makedirs(final_dir, exist_ok=True)
        # 复制文件
        for item in os.listdir(extract_dir):
            s = os.path.join(extract_dir, item)
            d = os.path.join(final_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
        # 写入 manifest
        with open(os.path.join(final_dir, 'manifest.json'), 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        # 注册到 PLUGIN_LIST
        if not any(p['id'] == pid for p in PLUGIN_LIST):
            PLUGIN_LIST.append({
                "id": pid,
                "name": manifest.get('name', pid),
                "type": manifest.get('type', 'custom'),
                "enabled": True,
                "icon": manifest.get('icon', '📦'),
                "config": {"data_file": os.path.join(final_dir, 'data.json')},
                "mapping": manifest.get('mapping', {})
            })
            save_plugin_config(PLUGIN_LIST)
        return {"ok": True, "id": pid, "name": manifest.get('name', pid)}
    finally:
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)

def install_plugin_from_url(url):
    """从 URL 下载并安装插件"""
    import tempfile
    if not url.startswith(('http://', 'https://')):
        return {"error": "链接必须以 http:// 或 https:// 开头"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PixivFavSearch/1.0"})
        tmp = tempfile.NamedTemporaryFile(suffix='.plug', delete=False)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                if len(data) > 50 * 1024 * 1024:
                    return {"error": "文件太大了（最大 50MB）"}
                tmp.write(data)
            tmp.close()
            result = _install_plugin_from_zip(tmp.name)
            return result
        except Exception as e:
            return {"error": f"下载失败: {repr(e)[:100]}"}
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)
    except Exception as e:
        return {"error": repr(e)[:200]}

def uninstall_plugin(pid):
    """卸载插件"""
    import shutil
    try:
        # 不能卸载内置 pixiv
        if pid == 'pixiv':
            return {"error": "不能卸载 Pixiv 数据源"}
        plugin = next((p for p in PLUGIN_LIST if p['id'] == pid), None)
        if not plugin:
            return {"error": "插件不存在"}
        # 删除目录
        pdir = _get_plugin_dir(pid)
        if os.path.exists(pdir):
            shutil.rmtree(pdir)
        # 删除 .plug 文件
        for fname in os.listdir(PLUGINS_DIR):
            if fname.endswith('.plug') and os.path.splitext(fname)[0] == pid:
                os.unlink(os.path.join(PLUGINS_DIR, fname))
        # 从列表移除
        PLUGIN_LIST[:] = [p for p in PLUGIN_LIST if p['id'] != pid]
        save_plugin_config(PLUGIN_LIST)
        # 清除缓存
        PLUGIN_DATA.pop(pid, None)
        return {"ok": True}
    except Exception as e:
        return {"error": repr(e)[:200]}

def fetch_market(url=None):
    """获取插件市场列表"""
    if not url:
        url = MARKET_URL_DEFAULT
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PixivFavSearch/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode('utf-8', 'ignore'))
        return {"ok": True, "plugins": data.get('plugins', []), "url": url}
    except Exception as e:
        return {"error": f"获取市场失败: {repr(e)[:100]}"}

def load_plugins():
    """加载所有启用的插件数据"""
    global PLUGIN_LIST
    PLUGIN_DATA.clear()
    
    for plugin in PLUGIN_LIST:
        if not plugin.get("enabled", False):
            continue
        result = _load_plugin(plugin)
        if "error" in result:
            log_error(f"插件 {plugin['id']} 加载失败: {result['error']} | Plugin load failed: {result['error']}")
        else:
            log_info(f"插件 {plugin['id']} 加载 {result['count']} 条 | Plugin loaded {result['count']} items")

def save_plugin_config(plugins):
    """保存插件配置到文件"""
    try:
        with open(PLUGIN_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"plugins": plugins}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        log_error(f"保存插件配置失败: {repr(e)} | Save plugin config failed: {repr(e)}")
        return False

def load_plugin_config():
    """从文件加载插件配置,不存在则用默认配置"""
    global PLUGIN_LIST
    
    if os.path.exists(PLUGIN_CONFIG_FILE):
        try:
            with open(PLUGIN_CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            PLUGIN_LIST = cfg.get("plugins", [])
            if PLUGIN_LIST:
                log_info(f"从文件加载 {len(PLUGIN_LIST)} 个插件配置 | Loaded {len(PLUGIN_LIST)} plugins from file")
                return
        except Exception as e:
            log_warn(f"插件配置加载失败,使用默认: {repr(e)} | Plugin config load failed, using defaults")
    
    # 默认配置
    PLUGIN_LIST = [
        {
            "id": "pixiv",
            "name": "Pixiv",
            "type": "builtin",
            "enabled": True,
            "icon": "📚",
            "config": {"data_file": "bookmarks.json"},
            "mapping": {
                "id": "id",
                "title": "title",
                "author": "userName",
                "thumb": "url",
                "tags": "tags",
                "url": "url",
                "desc": "description"
            }
        },
        {
            "id": "nhentai",
            "name": "nhentai",
            "type": "builtin",
            "enabled": False,
            "icon": "📖",
            "config": {"data_file": "nhentai收藏.json"},
            "mapping": {
                "id": "id",
                "title": "title",
                "author": "author",
                "thumb": "thumb",
                "tags": "tags",
                "url": "url",
                "desc": "desc"
            }
        },
        {
            "id": "iwara",
            "name": "iwara",
            "type": "builtin",
            "enabled": False,
            "icon": "🎬",
            "config": {"data_file": "iwara收藏.json"},
            "mapping": {
                "id": "id",
                "title": "title",
                "author": "author",
                "thumb": "thumb",
                "tags": "tags",
                "url": "url",
                "desc": "desc"
            }
        },
        {
            "id": "c18",
            "name": "18comic",
            "type": "builtin",
            "enabled": False,
            "icon": "🔞",
            "config": {"data_file": "18comic收藏.json"},
            "mapping": {
                "id": "id",
                "title": "title",
                "author": "author",
                "thumb": "thumb",
                "tags": "tags",
                "url": "url",
                "desc": "desc"
            }
        },
        {
            "id": "ehentai",
            "name": "e-hentai",
            "type": "builtin",
            "enabled": False,
            "icon": "📕",
            "config": {"data_file": "ehentai收藏.json"},
            "mapping": {
                "id": "id",
                "title": "title",
                "author": "author",
                "thumb": "thumb",
                "tags": "tags",
                "url": "url",
                "desc": "desc"
            }
        }
    ]
    save_plugin_config(PLUGIN_LIST)
    scan_plugins_dir()


# --- 内置更新检查(启动时后台查一次 GitHub 最新 release, 非强制) ---
LATEST_VER = {"checking": True, "ok": False, "version": None, "url": None}
def _check_update():
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/Hzm66647/PixivFavSearch/releases/latest",
            headers={"User-Agent": "PixivFavSearch/" + VERSION})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        v = (d.get("tag_name") or "").lstrip("v")
        LATEST_VER.update(checking=False, ok=True, version=v, url=d.get("html_url"))
    except Exception:
        LATEST_VER.update(checking=False, ok=False)
threading.Thread(target=_check_update, daemon=True).start()

def _ver_gt(a, b):
    """版本号 a > b? 1.2.3 > 1.1.9"""
    for x, y in zip(a.split("."), b.split(".")):
        if int(x) != int(y): return int(x) > int(y)
    return len(a.split(".")) > len(b.split("."))

ASSET_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
def asset_path(kind):
    """返回 pix_assets 下 banner.* / avatar.* 存在的文件路径,没有返回 None"""
    for f in os.listdir(ASSETS):
        if f.startswith(kind + "."):
            return os.path.join(ASSETS, f)
    return None

import re as _re
import pykakasi
_KAKASI = pykakasi.kakasi()

def romanize(s):
    """把标题中的假名转罗马音(小写),字母/汉字保留。生成跨语言检索别名。"""
    if not s: return ""
    parts = _re.split(r'([\u3040-\u30ff]+)', s)
    res = []
    for p in parts:
        if _re.fullmatch(r'[\u3040-\u30ff]+', p):
            try:
                res.append(''.join(x['hepburn'] for x in _KAKASI.convert(p)).lower())
            except Exception:
                res.append(p)
        else:
            res.append(p)
    return ''.join(res).lower()

# ===== 简繁/日文汉字归一化: 東方→东方, 让近义词/变体也能命中 =====
try:
    from opencc import OpenCC
    _T2S = OpenCC('t2s')
except Exception:
    _T2S = None

# opencc t2s 不覆盖的日文新字体(高频) → 简体 补丁
_JP_EXTRA = str.maketrans({
    "郷": "乡", "図": "图", "関": "关", "辺": "边", "駅": "站",
    "広": "广", "県": "县", "絵": "绘", "芸": "艺", "鉄": "铁",
    "読": "读", "語": "语", "説": "说", "話": "话", "調": "调",
    "線": "线", "続": "续", "網": "网", "経": "经", "総": "总",
    "統": "统", "訳": "译", "豊": "丰", "車": "车", "転": "转",
    "軽": "轻", "進": "进", "運": "运", "達": "达", "選": "选",
    "階": "阶", "際": "际", "雑": "杂", "難": "难", "響": "响",
    "頂": "顶", "顔": "颜", "風": "风", "飛": "飞", "飯": "饭",
    "飲": "饮", "館": "馆", "馬": "马", "鳥": "鸟", "黒": "黑",
    "歯": "齿", "齢": "龄", "竜": "龙", "売": "卖", "買": "买",
    "気": "气", "帰": "归", "観": "观", "覚": "觉", "強": "强",
    "検": "检", "権": "权", "師": "师", "実": "实", "収": "收",
    "従": "从", "渋": "涩", "書": "书", "勝": "胜", "条": "条",
    "乗": "乘", "場": "场", "数": "数", "声": "声", "静": "静",
    "節": "节", "積": "积", "絶": "绝", "戦": "战", "争": "争",
    "層": "层", "倉": "仓", "臓": "脏", "増": "增", "贈": "赠",
    "側": "侧", "卒": "卒", "孫": "孙", "損": "损", "対": "对",
    "帯": "带", "滞": "滞", "台": "台", "題": "题", "沢": "泽",
    "単": "单", "胆": "胆", "誕": "诞", "団": "团", "弾": "弹",
    "断": "断", "談": "谈", "値": "值", "着": "着", "沖": "冲",
    "駐": "驻", "帳": "帐", "張": "张", "徴": "征", "超": "超",
    "長": "长", "沈": "沉", "珍": "珍", "賃": "赁", "陳": "陈",
    "鎮": "镇", "墜": "坠", "低": "低", "底": "底", "弟": "弟",
    "点": "点", "伝": "传", "殿": "殿", "電": "电", "凍": "冻",
    "湯": "汤", "灯": "灯", "当": "当", "等": "等", "筒": "筒",
    "答": "答", "糖": "糖", "到": "到", "討": "讨", "東": "东",
    "頭": "头", "働": "动", "動": "动", "同": "同", "導": "导",
    "道": "道", "特": "特", "独": "独", "徳": "德", "突": "突",
    "届": "届", "曇": "昙", "鈍": "钝", "内": "内", "南": "南",
    "軟": "软", "認": "认", "寧": "宁", "熱": "热", "念": "念",
    "悩": "恼", "納": "纳", "脳": "脑", "濃": "浓", "派": "派",
    "破": "破", "覇": "霸", "廃": "废", "梅": "梅", "杯": "杯",
    "麦": "麦", "賠": "赔", "敗": "败", "倍": "倍", "培": "培",
    "陪": "陪", "媒": "媒", "晩": "晚", "番": "番", "盤": "盘",
    "比": "比", "皮": "皮", "疲": "疲", "被": "被", "避": "避",
    "備": "备", "筆": "笔", "必": "必", "姫": "姬", "票": "票",
    "標": "标", "漂": "漂", "病": "病", "秒": "秒", "浜": "滨",
    "貧": "贫", "頻": "频", "敏": "敏", "瓶": "瓶", "夫": "夫",
    "敷": "敷", "普": "普", "浮": "浮", "父": "父", "符": "符",
    "腐": "腐", "膚": "肤", "賦": "赋", "負": "负", "赴": "赴",
    "附": "附", "婦": "妇", "武": "武", "舞": "舞", "封": "封",
    "伏": "伏", "服": "服", "副": "副", "幅": "幅", "復": "复",
    "腹": "腹", "払": "拂", "沸": "沸", "仏": "佛", "物": "物",
    "分": "分", "噴": "喷", "紛": "纷", "雰": "氛", "文": "文",
    "聞": "闻", "併": "并", "兵": "兵", "米": "米", "閉": "闭",
    "陛": "陛", "平": "平", "弊": "弊", "並": "并", "柄": "柄",
    "別": "别", "片": "片", "返": "返", "変": "变", "便": "便",
    "勉": "勉", "歩": "步", "保": "保", "補": "补", "舗": "铺",
    "母": "母", "募": "募", "墓": "墓", "暮": "暮", "簿": "簿",
    "包": "包", "宝": "宝", "報": "报", "飽": "饱", "亡": "亡",
    "妨": "妨", "忘": "忘", "忙": "忙", "坊": "坊", "房": "房",
    "肪": "肪", "某": "某", "冒": "冒", "剖": "剖", "紡": "纺",
    "望": "望", "傍": "傍", "帽": "帽", "棒": "棒", "貿": "贸",
    "暴": "暴", "膨": "膨", "謀": "谋", "頬": "颊", "僕": "仆",
    "北": "北", "木": "木", "朴": "朴", "牧": "牧", "睦": "睦",
    "黙": "默", "墨": "墨", "本": "本", "翻": "翻", "凡": "凡",
    "盆": "盆", "麻": "麻", "摩": "摩", "磨": "磨", "魔": "魔",
    "毎": "每", "万": "万", "満": "满", "慢": "慢", "漫": "漫",
    "未": "未", "味": "味", "魅": "魅", "妙": "妙", "民": "民",
    "眠": "眠", "矛": "矛", "務": "务", "無": "无", "夢": "梦",
    "霧": "雾", "娘": "娘", "名": "名", "命": "命", "明": "明",
    "迷": "迷", "鳴": "鸣", "滅": "灭", "免": "免", "面": "面",
    "茂": "茂", "模": "模", "毛": "毛", "盲": "盲", "耗": "耗",
    "目": "目", "問": "问", "門": "门", "夜": "夜", "野": "野",
    "弥": "弥", "厄": "厄", "役": "役", "約": "约", "薬": "药",
    "躍": "跃", "愉": "愉", "油": "油", "癒": "愈", "諭": "谕",
    "輸": "输", "唯": "唯", "優": "优", "友": "友", "有": "有",
    "勇": "勇", "幽": "幽", "悠": "悠", "郵": "邮", "雄": "雄",
    "誘": "诱", "融": "融", "与": "与", "予": "予", "余": "余",
    "誉": "誉", "預": "预", "幼": "幼", "用": "用", "羊": "羊",
    "洋": "洋", "曜": "曜", "葉": "叶", "陽": "阳", "養": "养",
    "抑": "抑", "欲": "欲", "翌": "翌", "翼": "翼", "羅": "罗",
    "裸": "裸", "来": "来", "頼": "赖", "雷": "雷", "落": "落",
    "絡": "络", "酪": "酪", "乱": "乱", "卵": "卵", "覧": "览",
    "欄": "栏", "利": "利", "裏": "里", "理": "理", "痢": "痢",
    "履": "履", "離": "离", "陸": "陆", "立": "立", "律": "律",
    "略": "略", "柳": "柳", "流": "流", "留": "留", "粒": "粒",
    "隆": "隆", "僚": "僚", "両": "两", "凌": "凌", "料": "料",
    "涼": "凉", "猟": "猎", "陵": "陵", "量": "量", "領": "领",
    "力": "力", "緑": "绿", "倫": "伦", "輪": "轮", "隣": "邻",
    "臨": "临", "瑠": "琉", "累": "累", "塁": "垒", "涙": "泪",
    "類": "类", "令": "令", "礼": "礼", "励": "励", "戻": "回",
    "例": "例", "霊": "灵", "麗": "丽", "暦": "历", "歴": "历",
    "列": "列", "劣": "劣", "烈": "烈", "裂": "裂", "廉": "廉",
    "恋": "恋", "練": "练", "連": "连", "錬": "炼", "呂": "吕",
    "炉": "炉", "路": "路", "露": "露", "老": "老", "労": "劳",
    "弄": "弄", "朗": "朗", "浪": "浪", "楼": "楼", "漏": "漏",
    "論": "论", "和": "和", "賄": "贿", "惑": "惑", "枠": "框",
    "湾": "湾", "腕": "腕",
})

def _norm_cjk(s):
    """把繁体/日文汉字转简体, 用于变体匹配(东方↔東方)。"""
    if not s: return s
    out = s.translate(_JP_EXTRA)
    if _T2S is not None:
        try:
            out = _T2S.convert(out)
        except Exception:
            pass
    return out

# ===== 拼音检索: dongfang → 东方/東方 =====
try:
    from pypinyin import lazy_pinyin as _LAZY_PY
except Exception:
    _LAZY_PY = None

try:
    import jieba
except Exception:
    jieba = None

def _pinyin(s):
    """把中文转拼音全拼(小写, 支持繁体), 假名/英文原样保留。"""
    if not s or _LAZY_PY is None: return ""
    try:
        return "".join(_LAZY_PY(s)).lower()
    except Exception:
        return ""

def _pub(it, hl=None):
    """输出给前端前清洗内部 _ 索引字段, 附加高亮词列表。"""
    o = {k: v for k, v in it.items() if not k.startswith("_")}
    o["hl"] = hl or []
    return o

def _seg_query(q_lower):
    """jieba 分词: 无空格的中文组合词(东方灵梦→东方+灵梦)切成词, 供 AND 匹配。"""
    if jieba is None or not q_lower:
        return []
    try:
        return [s for s in jieba.lcut(q_lower) if len(s) >= 2 and not s.isspace() and not s.isascii()]
    except Exception:
        return []

# 预热 jieba 词典, 避免第一次搜索卡顿
if jieba is not None:
    try:
        jieba.initialize()
    except Exception:
        pass

def _hl_variant(title, q_norm):
    """标题通过简繁变体命中时, 找出标题里对应的原文片段用于高亮(校验索引对齐)。"""
    try:
        title = title or ""
        norm = _norm_cjk(title).lower()
        i = norm.find(q_norm)
        if i < 0:
            return []
        j = i + len(q_norm)
        if j <= len(title) and _norm_cjk(title[i:j]).lower() == q_norm:
            return [title[i:j]]
    except Exception:
        pass
    return []

# 音译同义词组: 组内任意写法(中文音译/日文原名/罗马字)命中都算
# 例: 琪露诺 = 琦露诺 = チルノ = Cirno; 搜任何一个都能带出同组所有作品
_HOMOPHONE_GROUPS = [
    ["琪露诺", "琦露诺", "奇露诺", "チルノ", "cirno"],
    ["灵梦", "霊夢", "れいむ", "reimu"],
    ["魔理沙", "霧雨魔理沙", "まりさ", "marisa"],
    ["芙兰朵露", "フランドール", "flandre"],
    ["蕾米莉亚", "レミリア", "remilia"],
    ["帕秋莉", "パチュリー", "patchouli"],
    ["幽幽子", "幽々子", "ゆゆこ", "yuyuko"],
    ["八云紫", "八雲紫", "ゆかり", "yukari"],
    ["琪亚娜", "キアナ", "kiana"],
    ["布洛妮娅", "ブローニャ", "bronya"],
]
# 构建 写法→整组 映射(搜组内任意写法都拿到整组)
_HOMO_MAP = {}
for _grp in _HOMOPHONE_GROUPS:
    _forms = [
        {"raw": _w, "low": _w.lower(), "py": _pinyin(_w).lower(), "rom": romanize(_w).lower()}
        for _w in _grp
    ]
    for _w in _grp:
        _HOMO_MAP.setdefault(_w.lower(), _forms)

def _get_homophones(q_lower):
    """返回 q 命中的音译同义词组(整组 forms), 无则 None。
    优先整词匹配(琪露诺→整词命中), 再退化到 jieba 分词(东方灵梦→灵梦)。"""
    if not q_lower:
        return None
    if q_lower in _HOMO_MAP:
        return _HOMO_MAP[q_lower]
    for w in (_seg_query(q_lower) or []):
        if w.lower() in _HOMO_MAP:
            return _HOMO_MAP[w.lower()]
    return None

def _match_score(it, q_lower, q_norm, q_rom, q_py, words, aliases=None, kana_roms=None, seg_words=None, homophones=None):
    """对单个条目打分排序。返回 (score, hitsrc, hl) 或 None(不命中)。
    score 越大越相关; hl 为前端高亮词(拼音/罗马音命中原词未必出现, 不高亮)。
    命中优先级: 标题原文 > 全字段原文 > 分词AND > 别名 > 简繁变体(标题) > 简繁变体(全字段)
               > 拼音(标题,含音译同音) > 拼音(全字段) > 假名罗马音 > 音译同义词组 > 跨语言 fuzzy
    """
    if not q_lower:
        return (0, "exact", [])
    t_search = it.get("_search", "")
    t_title = (it.get("title") or "").lower()
    t_norm = it.get("_norm", "")
    t_norm_title = it.get("_norm_title", "")
    t_search_py = it.get("_search_py", "")
    t_title_py = it.get("_title_py", "")
    t_search_rom = it.get("_search_rom", "")
    raw_title = it.get("title") or ""
    wl = [w.lower() for w in words]
    # 1) 标题原文精确子串(最相关)
    if q_lower in t_title:
        return (100, "exact", [q_lower])
    # 2) 全字段原文: 每个词都命中
    if all(w in t_search for w in wl):
        return (90, "exact", wl)
    # 2b) 分词匹配: 无空格组合词 全部命中(东方灵梦 → 东方+灵梦)
    if seg_words and len(seg_words) >= 2 and all(s in t_search for s in seg_words):
        return (88, "exact", seg_words)
    # 3) 别名命中: 东方 → touhou project(同义词, 高亮实际命中的别名)
    if aliases:
        al = [a for a in aliases if a.lower() in t_search]
        if al:
            return (85, "exact", al)
    # 4) 简繁/日文汉字变体: 标题 (东方↔東方)
    if q_norm and q_norm in t_norm_title:
        return (80, "exact", _hl_variant(raw_title, q_norm))
    # 5) 简繁/日文汉字变体: 全字段
    if q_norm and q_norm in t_norm:
        return (70, "exact", _hl_variant(raw_title, q_norm))
    # 6) 拼音/音译: 标题 (dongfang→东方, 琪露诺→琦露诺 同音)
    if q_py and q_py in t_title_py:
        return (75, "py", [])
    # 7) 拼音/音译: 全字段
    if q_py and q_py in t_search_py:
        return (65, "py", [])
    # 8) 假名罗马音整串
    if q_rom and q_rom in t_search_rom:
        return (60, "rom", [])
    # 8b) 假名片段单独匹配(如 アズサ→azusa)
    if kana_roms and any(kr and kr in t_search_rom for kr in kana_roms):
        return (60, "rom", [])
    # 8c) 音译同义词组: 琪露诺→チルノ/cirno/琦露诺 (中文译名↔日文原名↔罗马字)
    if homophones:
        for hp in homophones:
            if hp["low"] and hp["low"] in t_search:
                return (55, "exact", [hp["raw"]])
            if hp["rom"] and hp["rom"] in t_search_rom:
                return (55, "exact", [hp["raw"]])
            if hp["py"] and len(hp["py"]) >= 2 and hp["py"] in t_search_py:
                return (55, "exact", [hp["raw"]])
    # 9) 跨语言 fuzzy: 仅标题含假名 + 单关键词 + 查询本身也含假名(避免中文汉字编辑距离误判)
    if q_rom and len(words) == 1 and _re.search(r'[\u3040-\u30ff]', raw_title) and _re.search(r'[\u3040-\u30ff]', q_lower):
        if fuzzy_roman_match(q_rom, it.get("_title_rom", "")):
            return (50, "fuzzy", [])
    return None

def edit_distance(a, b):
    """朴素编辑距离(小串用)。"""
    if a == b: return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > 2 and min(la, lb) == 0: return max(la, lb)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0]*lb
        for j in range(1, lb + 1):
            cur[j] = min(cur[j-1]+1, prev[j]+1, prev[j-1] + (a[i-1]!=b[j-1]))
        prev = cur
    return prev[lb]

def fuzzy_roman_match(query_rom, title_rom):
    """罗马音宽松匹配:跨语言同题(如 plana ↔ purana)。"""
    if not query_rom or not title_rom: return False
    q, t = query_rom, title_rom
    # 1) 直接包含
    if q in t: return True
    # 2) 按空白拆分后,任一 token 编辑距离小
    qtoks = q.split()
    ttoks = t.lower().split()
    for qt in qtoks:
        if len(qt) < 3: continue
        for tt in ttoks:
            if len(tt) < 3: continue
            if abs(len(qt)-len(tt)) <= 2 and edit_distance(qt, tt) <= 2:
                return True
    return False

# 代理 + pximg 下载需 Referer 头
pysocks.set_default_proxy(pysocks.SOCKS5, "127.0.0.1", 10808)
pysocket.socket = pysocks.socksocket

def norm_tags(tags):
    out = []
    if isinstance(tags, list):
        for t in tags:
            if isinstance(t, dict): out.append(t.get("tag", ""))
            elif isinstance(t, str): out.append(t)
    elif isinstance(tags, str):
        out = [tags]
    return out

def _load_pixiv_data():
    """加载 pixiv 收藏数据。优先用户数据 bookmarks.json, 缺失则回退示例数据 demo_data.json。"""
    path = DATA
    fell_back = False
    if not os.path.exists(path):
        if os.path.exists(DEMO_DATA):
            path = DEMO_DATA
            fell_back = True
        else:
            # 两者都没有: 返回空列表(界面会提示先导出或放置数据)
            return [], 0.0
    return json.load(open(path, encoding="utf-8")), os.path.getmtime(path)

# 加载插件配置和数据
load_plugin_config()
load_plugins()

# 保持向后兼容: BOOKMARKS 指向 pixiv 插件数据
BOOKMARKS = PLUGIN_DATA.get("pixiv", [])
BOOKMARKS_LOAD_TIME = time.time()
if BOOKMARKS_LOAD_TIME == 0.0:
    _data_src = "no-data"
elif not os.path.exists(DATA):
    _data_src = "demo"
else:
    _data_src = "user"
import threading as _t
PIXIV_LOCK = _t.Lock()
# 预计算每幅的可检索映射:
# _title_rom: 标题假名→罗马音(跨语言)
# _search:    标题+标签+说明 原文串
# _search_rom: 同上 假名→罗马音
for it in BOOKMARKS:
    title = it.get("title") or ""
    tags = " ".join(norm_tags(it.get("tags")))
    desc = it.get("description") or ""
    alt = it.get("alt") or ""
    raw = " ".join(x for x in (title, tags, desc, alt) if x)
    it.setdefault("_title_rom", romanize(title).lower())
    it.setdefault("_search", raw.lower())
    it.setdefault("_search_rom", romanize(raw).lower())
    it.setdefault("_norm", _norm_cjk(raw).lower())
    it.setdefault("_norm_title", _norm_cjk(title).lower())
    it.setdefault("_search_py", _pinyin(raw).lower())
    it.setdefault("_title_py", _pinyin(title).lower())
print(f"加载 {len(BOOKMARKS)} 幅书签(标题/标签/说明全字段索引 + 跨语言)")
def _build_pixiv_index(bookmarks):
    """对书签列表重建可检索索引字段(标题/标签/说明 全字段+跨语言)"""
    for it in bookmarks:
        title = it.get("title") or ""
        tags = " ".join(norm_tags(it.get("tags")))
        desc = it.get("description") or ""
        alt = it.get("alt") or ""
        raw = " ".join(x for x in (title, tags, desc, alt) if x)
        it.setdefault("_title_rom", romanize(title).lower())
        it.setdefault("_search", raw.lower())
        it.setdefault("_search_rom", romanize(raw).lower())
        it.setdefault("_norm", _norm_cjk(raw).lower())
        it.setdefault("_norm_title", _norm_cjk(title).lower())
        it.setdefault("_search_py", _pinyin(raw).lower())
        it.setdefault("_title_py", _pinyin(title).lower())

def reload_pixiv_if_changed():
    """pixiv 数据文件被导出脚本更新时热重载(增量)。每次搜索前调用。"""
    global BOOKMARKS, BOOKMARKS_LOAD_TIME
    try:
        mtime = os.path.getmtime(DATA)
    except Exception:
        return
    if mtime <= BOOKMARKS_LOAD_TIME:
        return
    with PIXIV_LOCK:
        try:
            mtime = os.path.getmtime(DATA)
        except Exception:
            return
        if mtime <= BOOKMARKS_LOAD_TIME:
            return
        try:
            data = json.load(open(DATA, encoding="utf-8"))
            _build_pixiv_index(data)
            BOOKMARKS = data
            BOOKMARKS_LOAD_TIME = mtime
            print(f"pixiv 数据热更新: {len(BOOKMARKS)} 幅书签")
            log_info(f"收藏数据热更新 {len(BOOKMARKS)} 条 | Bookmark data hot-reloaded: {len(BOOKMARKS)} items")
            # 后台预下载缩略图 (服务端进程, 不会被杀)
            import threading as _thr
            _thr.Thread(target=_prefetch_thumbnails_bg, daemon=True).start()
        except Exception as e:
            print("pixiv 热更新失败:", repr(e))
            log_error(f"收藏数据热更新失败: {repr(e)} | Bookmark hot-reload failed: {repr(e)}")

_PREFETCH_SEM = threading.Semaphore(3)  # 预下载并发限制

def _prefetch_thumbnails_bg():
    """后台预下载缺失缩略图 (在服务端运行, 进程存活则持续下载)"""
    time.sleep(0.5)
    missing = []
    for item in BOOKMARKS:
        pid = str(item.get("id", ""))
        local = os.path.join(THUMB, pid + ".jpg")
        if not (os.path.exists(local) and os.path.getsize(local) > 500):
            missing.append(item)
    if not missing:
        return
    log_info(f"开始预下载 {len(missing)} 个缺失缩略图 | Prefetching {len(missing)} missing thumbnails")
    count = 0
    for item in missing:
        pid = str(item.get("id", ""))
        local = os.path.join(THUMB, pid + ".jpg")
        url = item.get("url", "")
        if not url or "i.pximg.net" not in url:
            url = _fetch_thumb_url_from_api(pid)
            if not url:
                continue
        with _PREFETCH_SEM:
            try:
                req = urllib.request.Request(url, headers={
                    "Referer": "https://www.pixiv.net/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                })
                proxies = urllib.request.getproxies()
                opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies)) if proxies else urllib.request.build_opener()
                with opener.open(req, timeout=12) as r:
                    data = r.read(5 * 1024 * 1024 + 1)
                if len(data) > 5 * 1024 * 1024:
                    continue
                with open(local, "wb") as f:
                    f.write(data)
                if os.path.getsize(local) > 500:
                    count += 1
            except:
                pass
    log_info(f"缩略图预下载完成: {count}/{len(missing)} | Thumbnail prefetch done: {count}/{len(missing)}")

# --- 收藏导入/更新(CDP 抓取最新收藏) ---
_import_state = {"running": False, "code": None, "msg": "", "count": 0, "t": 0.0}

def import_status():
    """返回当前导入状态(供前端轮询)。t 为完成时间戳, 前端用于判断是否新一轮完成。"""
    s = dict(_import_state)
    return s

def _import_worker():
    """后台线程: 调用 pixiv_export.main() 抓取收藏, 写 bookmarks.json 后触发热重载。

    同时把 pixiv_export 的 stdout/stderr 逐行转发到日志(DEBUG), 方便诊断卡点。
    """
    global _import_state
    log_info("开始导入收藏 | Import bookmarks started")
    import io as _io
    import contextlib as _ctx
    _buf = _io.StringIO()
    try:
        with _ctx.redirect_stdout(_buf), _ctx.redirect_stderr(_buf):
            import pixiv_export as _ex
            code = _ex.main()
        # 把子模块的 print 输出逐行写入日志(DEBUG), 便于定位失败阶段
        for _line in _buf.getvalue().splitlines():
            if _line.strip():
                log_debug(f"[pixiv_export] {_line} | {_line}")
        count = len(BOOKMARKS)
        # 触发热重载(每次搜索前也会自动检查, 这里主动重载一次)
        reload_pixiv_if_changed()
        count = len(BOOKMARKS)
        if code == 0:
            msg = f"导入完成, 当前共 {count} 幅收藏"
            log_info(f"收藏导入完成, 共 {count} 幅 | Import finished, {count} bookmarks")
        else:
            msg = "导入失败。已尝试自动启动调试浏览器, 请在弹出的 Pixiv 页面确认已登录, 再点一次导入"
            log_error(f"收藏导入失败(code={code}) | Import failed (code={code})")
        _import_state.update({"running": False, "code": code, "msg": msg, "count": count, "t": time.time()})
    except Exception as e:
        # 异常时也要把已缓存的子模块输出写入日志
        for _line in _buf.getvalue().splitlines():
            if _line.strip():
                log_debug(f"[pixiv_export] {_line} | {_line}")
        log_error(f"收藏导入异常: {repr(e)} | Import exception: {repr(e)}")
        _import_state.update({"running": False, "code": -1, "msg": f"导入异常: {repr(e)}", "count": 0, "t": time.time()})

def start_import():
    """启动导入任务。已在跑则返回 False。"""
    if _import_state["running"]:
        return False
    _import_state.update({"running": True, "code": None, "msg": "导入中…", "count": 0, "t": 0.0})
    import threading as _thr
    _thr.Thread(target=_import_worker, daemon=True).start()
    return True

# 中文/日文别名 → 英文标签/角色名(多语言关联, 中文搜索也能命中)
NH_ALIAS = {
    "碧蓝档案": ["blue archive"], "蔚蓝档案": ["blue archive"], "ブルアカ": ["blue archive"], "ブルーアーカイブ": ["blue archive"],
    "白洲梓": ["azusa"], "白洲アズサ": ["azusa"], "アズサ": ["azusa"],
    "砂狼白子": ["shiroko"], "白子": ["shiroko"],
    "小鸟游星野": ["hoshino"], "星野": ["hoshino"],
    "十六夜野宫": ["nonomi"], "野宫": ["nonomi"],
    "奥空绫音": ["ayane"], "绫音": ["ayane"],
    "陆八魔亚瑠": ["aru"], "亚瑠": ["aru"],
    "鬼方佳代子": ["kayoko"], "佳代子": ["kayoko"],
    "伊草春香": ["haruka"], "春香": ["haruka"],
    "才羽桃井": ["momoi"], "桃井": ["momoi"],
    "才羽绿": ["midori"],
    "天童爱丽丝": ["alice"], "爱丽丝": ["alice"],
    "早濑优香": ["yuuka"], "优香": ["yuuka"],
    "黑见芹香": ["serika"], "芹香": ["serika"],
    "阿慈谷日富美": ["hifumi"], "日富美": ["hifumi"],
    "一之濑明日奈": ["asuna"], "明日奈": ["asuna"],
    "河和静子": ["shizuko"], "静子": ["shizuko"],
    "小涂真纪": ["maki konuri"], "真纪": ["maki konuri"],
    "浅黄睦月": ["mutsuki"], "睦月": ["mutsuki"],
    "狐坂若藻": ["wakamo"], "若藻": ["wakamo"],
    "久田泉奈": ["izuna"], "泉奈": ["izuna"],
    "月雪宫子": ["miyako"], "宫子": ["miyako"],
    "空井咲": ["saki"], "咲": ["saki"],
    "霞泽美游": ["miyu"], "美游": ["miyu"],
    "春日椿": ["tsubaki"], "椿": ["tsubaki"],
    "阿拜多斯": ["abydos"], "圣三一": ["trinity"], "格黑娜": ["gehenna"], "千年": ["millennium"],
    "精灵宝可梦": ["pokemon"], "宝可梦": ["pokemon"], "ポケモン": ["pokemon"],
    "原神": ["genshin impact"], "崩坏星穹铁道": ["honkai star rail"], "崩坏3": ["honkai impact"],
    "明日方舟": ["arknights"], "碧蓝航线": ["azur lane"], "东方project": ["touhou project"], "东方": ["touhou project"],
    "舰队collection": ["kantai collection"], "舰娘": ["kantai collection"],
    "fate": ["fate"], "型月": ["fate"], "fgo": ["fate grand order"], "命运冠位指定": ["fate grand order"],
    "赛马娘": ["uma musume"], "马娘": ["uma musume"],
    "偶像大师": ["idolmaster"], "爱马仕": ["idolmaster"],
    "孤独摇滚": ["bocchi the rock"], "电锯人": ["chainsaw man"], "咒术回战": ["jujutsu kaisen"],
    "绝区零": ["zenless zone zero"], "zzz": ["zenless zone zero"], "空洞骑士": ["hollow knight"],
    "别当欧尼酱了": ["onii-chan wa oshimai"],
    "为美好的世界献上祝福": ["kono subarashii sekai ni syukufuku o"], "素晴": ["kono subarashii sekai ni syukufuku o"],
    "clannad": ["clannad"], "无职转生": ["mushoku tensei"],
    "约会大作战": ["date a live"], "租借女友": ["kanojo okarishimasu"],
    "hololive": ["hololive"], "彩虹社": ["nijisanji"],
    "凉宫春日的忧郁": ["the melancholy of haruhi suzumiya"], "凉宫春日": ["the melancholy of haruhi suzumiya"],
    "公主连结": ["princess connect"], "公主连接": ["princess connect"],
    "刀剑神域": ["sword art online"], "sao": ["sword art online"],
    "青春猪头少年": ["seishun buta yarou"], "青春猪头": ["seishun buta yarou"],
    "你的名字": ["kimi no na wa"], "摇曳露营": ["yuru camp"], "龙与虎": ["toradora"],
    "re零": ["re zero"], "从零开始的异世界生活": ["re zero"],
    "邦邦": ["bang dream"], "边狱公司": ["limbus company"],
    "中二病也要谈恋爱": ["chuunibyou demo koi ga shitai"], "中二病": ["chuunibyou demo koi ga shitai"],
    "lovelive": ["love live"], "love live": ["love live"], "爱生活": ["love live"],
    "出包王女": ["to love-ru"], "to love": ["to love-ru"],
    "物语系列": ["monogatari"], "俺妹": ["oreimo"], "埃罗芒阿老师": ["eromanga sensei"],
    "五等分的新娘": ["gotoubun no hanayome"], "五等分": ["gotoubun no hanayome"],
    "间谍过家家": ["spy x family"], "鬼灭之刃": ["kimetsu no yaiba"],
    "进击的巨人": ["shingeki no kyojin"], "进击": ["shingeki no kyojin"],
    "夏日重现": ["summer time rendering"], "葬送的芙莉莲": ["sousou no frieren"],
    "芙莉莲": ["sousou no frieren"], "我推的孩子": ["oshi no ko"], "推子": ["oshi no ko"],
    "少女前线": ["girls frontline"], "少前": ["girls frontline"],
    "明日方舟终末地": ["arknights endfield"], "终末地": ["arknights endfield"],
    "绝区零": ["zenless zone zero"],
    "像素工厂": ["mindustry"], "王国风云": ["crusader kings"], "群星": ["stellaris"],
}

# 加载收藏标签分类(用户自建 #收藏标签): {tag: [works]}
COLTAG_MAP = {}
COLTAG_META = {}
if os.path.exists(COLTAGS):
    try:
        raw = json.load(open(COLTAGS, encoding="utf-8"))
        _byid = {}
        for tag, works in raw.items():
            if not works: 
                COLTAG_MAP[tag] = []
                continue
            # 提取该标签下的作品id
            ids = set()
            for w in works:
                if isinstance(w, dict) and w.get("id"): ids.add(str(w["id"]))
                elif isinstance(w, str): ids.add(w)
            if not ids:
                # 可能是 {id:...} 结构?或直接列表了id
                pass
            COLTAG_MAP[tag] = ids
        print("加载收藏标签分类:", {t: len(v) for t, v in COLTAG_MAP.items()})
    except Exception as e:
        print("收藏标签加载失败:", repr(e))

THUMB_LOCK = threading.Lock()
THUMB_SEM = threading.Semaphore(3)

# demo 模式的示例占位图配色(每组 2 色渐变, 由 id 哈希决定, 稳定不闪变)
_DEMO_PALETTES = [
    ("#ff9a9e", "#fad0c4"), ("#a18cd1", "#fbc2eb"), ("#fbc2eb", "#a6c1ee"),
    ("#84fab0", "#8fd3f4"), ("#fccb90", "#d57eeb"), ("#f6d365", "#fda085"),
    ("#f093fb", "#f5576c"), ("#4facfe", "#00f2fe"), ("#43e97b", "#38f9d7"),
    ("#fa709a", "#fee140"), ("#30cfd0", "#330867"), ("#a8edea", "#fed6e3"),
]
def demo_thumb_svg(item, lang="zh"):
    """demo 数据(未导入收藏时)的本地占位图: 渐变色背景 + 占位文字(标题/作者/PID 用示例文案, 不泄露真实收藏)。
    lang='en' 时文字为英文占位(Title/Author/Sample), 否则中文(标题/作者/示例)。纯本地生成, 不依赖网络。"""
    pid = str(item.get("id", ""))
    en = lang == "en"
    title = "Title" if en else "标题"
    author = "Author" if en else "作者"
    pid_lbl = "Sample" if en else "示例"
    h = 0
    for ch in pid:
        h = (h * 31 + ord(ch)) & 0xffff
    c1, c2 = _DEMO_PALETTES[h % len(_DEMO_PALETTES)]
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
            '<rect width="400" height="400" fill="url(#g)"/>'
            '<rect x="8" y="8" width="384" height="384" rx="10" fill="rgba(255,255,255,0.08)"/>'
            f'<text x="200" y="120" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="64" fill="rgba(255,255,255,0.35)">🖼</text>'
            f'<text x="200" y="215" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="26" font-weight="600" fill="#fff">{title}</text>'
            f'<text x="200" y="255" text-anchor="middle" font-family="Segoe UI,Arial,sans-serif" font-size="17" fill="rgba(255,255,255,0.92)">{author}</text>'
            f'<text x="20" y="380" font-family="Consolas,monospace" font-size="13" fill="rgba(255,255,255,0.55)">{pid_lbl} {pid}</text>'
            '<text x="380" y="380" text-anchor="end" font-family="Segoe UI,Arial,sans-serif" font-size="13" fill="rgba(255,255,255,0.55)">PixivFavSearch demo</text>'
            '</svg>')

def thumb_for(item, lang="zh"):
    """返回本地缩略图路径(不存在则下载, 受并发信号量限制避免占满线程池)。
    demo 数据(未导入收藏)直接返回本地 SVG 占位图。lang 参数只在 demo 模式生效(控制 SVG 占位文字语言)。"""
    # demo 模式: 不尝试下载, 直接返回本地占位图
    if _data_src == "demo":
        pid = str(item["id"])
        svg = demo_thumb_svg(item, lang)
        _demo_dir = os.path.join(OUT, "demo_thumbs")
        try:
            os.makedirs(_demo_dir, exist_ok=True)
        except Exception:
            pass
        # lang 写入文件名, 避免 zh/en 缓存互相污染
        demo_local = os.path.join(_demo_dir, pid + ("_en.svg" if lang == "en" else "_zh.svg"))
        try:
            with open(demo_local, "w", encoding="utf-8") as f:
                f.write(svg)
            return demo_local
        except Exception:
            return None
    pid = str(item["id"])
    local = os.path.join(THUMB, pid + ".jpg")
    if os.path.exists(local) and os.path.getsize(local) > 500:
        return local
    url = item.get("url", "")
    if not url or "i.pximg.net" not in url:
        # url 缺失或不是图片 URL, 尝试从 pixiv API 获取
        url = _fetch_thumb_url_from_api(pid)
        if not url:
            return None
    # 并发限制: 同时最多 3 个下载, 防止 200 张卡片请求占满服务线程
    with THUMB_SEM:
        # 二次检查(可能在排队期间已下载)
        if os.path.exists(local) and os.path.getsize(local) > 500:
            return local
        try:
            req = urllib.request.Request(url, headers={
                "Referer": "https://www.pixiv.net/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            })
            # 禁重定向: 防 SSRF 跳内网
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **k):
                    return None
            # 走系统代理 (v2rayN 等)
            proxies = urllib.request.getproxies()
            if proxies:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), NoRedirect)
            else:
                opener = urllib.request.build_opener(NoRedirect)
            with opener.open(req, timeout=12) as r, open(local, "wb") as f:
                data = r.read(5 * 1024 * 1024 + 1)
                if len(data) > 5 * 1024 * 1024:
                    return None
                f.write(data)
            return local if os.path.getsize(local) > 500 else None
        except Exception as e:
            # 日志: 缩略图下载失败原因 (首次失败时打印)
            if not hasattr(thumb_for, '_err_logged'):
                thumb_for._err_logged = set()
            err_key = type(e).__name__
            if err_key not in thumb_for._err_logged:
                thumb_for._err_logged.add(err_key)
                log_warn(f"缩略图下载失败: {e} | Thumb download failed: {e}")
            return None

# pixiv API 获取缩略图 URL (缓存)
_thumb_url_cache = {}
def _fetch_thumb_url_from_api(pid):
    """从 pixiv API 获取作品缩略图 URL"""
    if pid in _thumb_url_cache:
        return _thumb_url_cache[pid]
    try:
        api_url = f"https://www.pixiv.net/ajax/illust/{pid}?lang=zh"
        req = urllib.request.Request(api_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            "Referer": "https://www.pixiv.net/",
        })
        proxies = urllib.request.getproxies()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies)) if proxies else urllib.request.build_opener()
        with opener.open(req, timeout=10) as resp:
            data = json.loads(resp.read())
        body = data.get("body", {})
        # 优先用 custom-thumb, 其次 img-master
        url = (body.get("urls", {}).get("thumb") or 
               body.get("urls", {}).get("small") or 
               body.get("urls", {}).get("mini") or "")
        if url and "i.pximg.net" in url:
            _thumb_url_cache[pid] = url
            return url
    except:
        pass
    _thumb_url_cache[pid] = None
    return None

# ========== 局域网访问安全(白名单 + Host校验 + 访问令牌 + 限速) ==========
# 只放行本机 + 手动添加的设备 IP。其余局域网设备一律 403。
# 手机 IP 请加进下面集合, 例如: ALLOWED_IPS = {"127.0.0.1", "::1", "192.168.0.101"}
# 注: IPv6 回环 ::1 也要保留, 否则某些浏览器本机访问会失败。
ALLOWED_IPS = {"127.0.0.1", "::1", "192.168.0.181"}

# Host 头白名单: 挡 DNS rebinding(恶意网页借本机通道读数据)。
# 只接受这些 Host, 其余(含任意攻击者域名)一律拒绝。
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "192.168.0.30"}

# 访问令牌: 非本机设备(手机)访问必须带 ?key=<ACCESS_KEY> 或已种下的 Cookie。
# 即使攻击者伪造手机 IP(ARP欺骗)也进不来。本机访问无需 key。
ACCESS_KEY = "qLCzN68J-767zrEl"

# 缩略图下载域名白名单: 代理只允许拉取这些域名下的图, 防数据文件被篡改时 SSRF。
THUMB_ALLOW_HOSTS = ("pximg.net",)

# API 限速: 每 IP 每 5 秒最多 60 次 /api/ 请求(图片代理不限, 浏览器并发拉图不误伤)
_RATE = {}
_RATE_LOCK = threading.Lock()

# token(ACCESS_KEY) → 种 Cookie 时的来源IP 绑定: 防嗅探的 Cookie 在其他IP重放。
# 手机换 IP 会误伤 → 需先做路由器 DHCP 静态保留。值为 {ip: timestamp} 便于清理。
_TOKEN_IP = {}
_TOKEN_IP_LOCK = threading.Lock()

class H(BaseHTTPRequestHandler):
    timeout = 10  # socket 超时(秒): 防慢速 DoS, 慢连接占用线程超时自动回收

    def log_message(self, *a): pass

    def _ip_ok(self):
        """检查客户端 IP 是否在白名单内"""
        ip = self.client_address[0]
        if ip in ALLOWED_IPS:
            return True
        # 允许通过配置的环境变量添加额外 IP(逗号分隔), 便于不改代码加设备
        extra = os.environ.get("PIX_ALLOW_IPS", "")
        if extra:
            for e in extra.split(","):
                if e.strip() == ip:
                    return True
        return False

    def _host_ok(self):
        """校验 Host 头, 挡 DNS rebinding"""
        host = self.headers.get("Host") or ""
        try:
            hn = (urllib.parse.urlsplit("//" + host).hostname or "").strip().lower()
        except Exception:
            return False
        if hn in ALLOWED_HOSTS:
            return True
        # 白名单内的客户端(含手机)访问本机私网 IP 时放行 — 电脑 IP 变化不影响手机访问
        ip = self.client_address[0]
        if ip in ALLOWED_IPS:
            try:
                import ipaddress
                if ipaddress.ip_address(hn).is_private:
                    return True
            except Exception:
                pass
        extra = os.environ.get("PIX_ALLOW_HOSTS", "")
        if extra:
            for e in extra.split(","):
                if e.strip().lower() == hn:
                    return True
        return False

    def _auth_ok(self):
        """非本机设备必须带访问令牌(key参数或Cookie); 本机免key"""
        ip = self.client_address[0]
        if ip in ("127.0.0.1", "::1"):
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if (q.get("key") or [""])[0] == ACCESS_KEY:
            self._set_cookie = True
            return True
        ck = self.headers.get("Cookie") or ""
        if f"pixkey={ACCESS_KEY}" in ck:
            # token 绑定 IP: Cookie 只认种下时的来源IP, 换IP重放 → 拒绝(防嗅探)
            with _TOKEN_IP_LOCK:
                bound = _TOKEN_IP.get(ACCESS_KEY)
                if bound is None:
                    # 服务重启后首次见 Cookie: 绑定当前 IP(向后兼容, 之后固定)
                    _TOKEN_IP[ACCESS_KEY] = ip
                    bound = ip
            if bound != ip:
                return False
            return True
        return False

    def _rate_ok(self):
        """API 限速: 每IP 5秒窗口最多60次 /api/; 图片代理宽松限速(100/5s, 防枚举触发远程下载);
        首页带 ?key= 的请求也限速(30/5s, 防 key 暴力枚举; 正常访问首页无 key 不受限)。"""
        ip = self.client_address[0]
        now = time.time()
        if self.path.startswith("/api/"):
            cap = 60
        elif self.path.startswith("/thumb/"):
            cap = 100
        elif self.path.startswith("/") and "key=" in self.path:
            cap = 30  # key 校验端点: 防暴力枚举
        else:
            return True
        with _RATE_LOCK:
            t = [x for x in _RATE.get(ip, []) if now - x < 5.0]
            # 防 _RATE 无限增长: 每 IP 窗口最多 cap 条, 超出即视为超限
            if len(t) >= cap:
                _RATE[ip] = t
                return False
            t.append(now)
            _RATE[ip] = t
            # 防 IP 条目无限增长: 超过 200 个 IP 时清理过期条目
            if len(_RATE) > 200:
                dead = [k for k, v in _RATE.items() if not v or now - v[-1] >= 5.0]
                for k in dead:
                    _RATE.pop(k, None)
        return True

    def _body_ok(self):
        """限制请求体大小, 防内存 DoS (最大 20MB)"""
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            return False
        return True

    def _safe_thumb_url(self, url):
        """缩略图URL域名白名单校验"""
        try:
            hn = (urllib.parse.urlsplit(url).hostname or "").lower()
        except Exception:
            return False
        return any(hn == h or hn.endswith("." + h) for h in THUMB_ALLOW_HOSTS)

    def _safe_download(self, url, timeout=15, max_bytes=5*1024*1024, proxy=False):
        """安全下载: 禁重定向(防SSRF跳内网) + 大小上限 + 图片魔数校验。
        返回 (ok, data_bytes) 或 (False, 原因)。"""
        # ① 下载前白名单复查(防止调用方漏查)
        if not self._safe_thumb_url(url):
            return False, "domain"
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                "Referer": urllib.parse.urlsplit(url).scheme + "://" + urllib.parse.urlsplit(url).netloc + "/",
            })
            if proxy:
                ph = urllib.request.ProxyHandler({"https": "socks5://127.0.0.1:10808", "http": "socks5://127.0.0.1:10808"})
                op = urllib.request.build_opener(ph)
            else:
                # ② 禁重定向: 自定义 handler, 302/301/303/307/308 一律不跟随
                class NoRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self, *a, **k):
                        return None
                op = urllib.request.build_opener(NoRedirect)
            with op.open(req, timeout=timeout) as r:
                # ③ 若上游仍返回重定向状态码, 拒绝
                if r.status in (301, 302, 303, 307, 308):
                    return False, "redirect"
                data = r.read(max_bytes + 1)  # ④ 大小上限: 多读1字节判断超限
                if len(data) > max_bytes:
                    return False, "too_big"
                # ⑤ 图片魔数校验: JPEG/PNG/GIF/WebP
                if not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"
                        or data[:6] in (b"GIF87a", b"GIF89a") or data[:4] == b"RIFF"):
                    return False, "not_image"
                return True, data
        except Exception as e:
            return False, repr(e)[:60]

    def _origin_ok(self):
        """Origin/Referer 校验, 挡恶意网页 CSRF/图片探测打到 localhost。
        有 Origin/Referer 且来源不在本机/私网白名单 → 拒绝(跨站请求)。
        无 Origin/Referer(curl/爬虫/直接导航) → 放行; Origin:null(file页面/沙箱iframe) → 拒绝。"""
        o = self.headers.get("Origin") or self.headers.get("Referer") or ""
        if not o:
            return True
        if o.strip().lower() == "null":
            return False
        try:
            hn = (urllib.parse.urlsplit(o).hostname or "").strip().lower()
        except Exception:
            return False
        if hn in ("127.0.0.1", "localhost", "::1"):
            return True
        if hn in ALLOWED_IPS:
            return True
        try:
            import ipaddress
            if ipaddress.ip_address(hn).is_private:
                return True
        except Exception:
            pass
        return False

    def _deny(self, code=403, msg="Forbidden: not allowed. (pix_search_server)"):
        self.send_response(code)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(msg.encode("utf-8"))

    def do_GET(self):
        try:
            self._handle_get()
        except Exception:
            # 畸形请求/异常: 不落 traceback(防搜索词泄露到日志), 统一 400
            try:
                self._deny(400, "Bad Request (pix_search_server)")
            except Exception:
                pass

    def _handle_get(self):
        _start_t = time.time()
        if not (self._ip_ok() and self._host_ok()):
            log_warn(f"拒绝访问: IP/Host 不在白名单 | Access denied: IP/Host not in whitelist")
            self._deny()
            return
        if not self._origin_ok():
            self._deny()
            return
        if not self._auth_ok():
            self._deny()
            return
        if not self._body_ok():
            self._deny(413, "Payload Too Large (pix_search_server)")
            return
        if not self._rate_ok():
            self._deny(429, "Too Many Requests (pix_search_server)")
            return
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            log_debug(f"GET / 首页 | GET / index page")
            if getattr(self, "_set_cookie", False):
                # key 用后即清: 已种 Cookie, 302 跳到无 key 的 URL, key 不进地址栏/历史/日志
                self.send_response(302)
                self.send_header("Location", "/")
                self._sec_headers()
                self.end_headers()
                return
            self.send_html(INDEX.replace("__DATASRC__", _data_src))
        elif u.path == "/api/search":
            mode = urllib.parse.parse_qs(u.query).get("mode", ["pixiv"])[0].strip()
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0].strip()
            tagf = urllib.parse.parse_qs(u.query).get("tag", [""])[0].strip().lower()
            colt = urllib.parse.parse_qs(u.query).get("coltag", [""])[0].strip()
            q_lower = q.lower()
            # 搜索词脱敏: 只记长度不记内容(防隐私泄露到日志)
            log_debug(f"搜索: 关键词长度={len(q)}, 标签={tagf or '-'}, 收藏标签={colt or '-'} | Search: q_len={len(q)}, tag={tagf or '-'}, coltag={colt or '-'}")
            load_plugins()  # 插件数据热重载(检测文件变化)
            q_rom = romanize(q).lower()
            q_norm = _norm_cjk(q).lower()
            q_py = _pinyin(q).lower()
            aliases = [a for k, v in NH_ALIAS.items() if k in q for a in v]
            words = [w for w in q.split() if w]
            seg_words = _seg_query(q_lower)
            homophones = _get_homophones(q_lower)
            # 选中的收藏标签允许的作品id集
            coltag_ids = COLTAG_MAP.get(colt) if colt else None
            # 空关键词:进入浏览模式(仅按标签过滤,输词才做匹配)。仅当有力选标签或确实无词全览时
            scored = []
            merged = []
            # 获取当前模式对应的数据源
            if mode == "pixiv":
                source_data = BOOKMARKS
            else:
                source_data = PLUGIN_DATA.get(mode, [])
            
            for it in source_data:
                # 限定收藏标签(coltag):作品必须属于该收藏标签(仅pixiv)
                if mode == "pixiv" and coltag_ids is not None and str(it.get("id")) not in coltag_ids:
                    continue
                # 限定作品标签过滤:作品的所有标签中要有一个等于 tagf
                tagset = { (t.get("tag") if isinstance(t, dict) else str(t)).lower() for t in (it.get("tags") or []) }
                tagset -= {""}
                if tagf and tagf not in tagset:
                    continue
                if not words:
                    # 空搜索: 不排序, 保持收藏原始顺序(不进入 scored)
                    merged.append(_pub(it, []))
                    continue
                res = _match_score(it, q_lower, q_norm, q_rom, q_py, words, aliases, None, seg_words, homophones)
                if res:
                    score, hitsrc, hl = res
                    scored.append((score, hitsrc, it, hl))
            # 按相关度排序(同分保持收藏顺序稳定)
            scored.sort(key=lambda x: (-x[0], x[2].get("id", "")))
            merged += [_pub(it, hl) for _, _, it, hl in scored]
            self.send_json(200, {"total": len(merged), "items": merged[:200]})
        elif u.path == "/api/version":
            # 返回当前版本 + 是否有新版本(启动时后台查过 GitHub)
            v = LATEST_VER
            self.send_json(200, {
                "current": VERSION,
                "checking": v.get("checking", False),
                "ok": v.get("ok", False),
                "latest": v.get("version"),
                "url": v.get("url"),
                "update": bool(v.get("ok") and v.get("version") and _ver_gt(v["version"], VERSION)),
            })
        elif u.path == "/api/coltags":
            # 返回用户自建收藏标签(带数量),供前端下拉
            ct = [{"tag": k, "count": len(v)} for k, v in sorted(COLTAG_MAP.items(), key=lambda x: -len(x[1]))]
            self.send_json(200, {"total": len(ct), "tags": ct})
        elif u.path == "/api/tags":
            # 返回用户所有收藏标签(去重+词频),供前端下拉
            c = {}
            for it in BOOKMARKS:
                for t in (it.get("tags") or []):
                    tag = (t.get("tag") if isinstance(t, dict) else str(t)).strip()
                    if not tag: continue
                    c[tag] = c.get(tag, 0) + 1
            tags = [{"tag": k, "count": v} for k, v in sorted(c.items(), key=lambda x: -x[1])]
            self.send_json(200, {"total": len(tags), "tags": tags})
        elif u.path == "/api/import":
            # 从 Pixiv 抓取最新收藏(CDP, cookie 不落盘)。POST 启动, 完成后热重载
            if self.command == "POST":
                started = start_import()
                self.send_json(200, {"ok": True, "started": started})
            else:
                st = import_status()
                self.send_json(200, st)
        elif u.path == "/api/import-status":
            self.send_json(200, import_status())
        elif u.path.startswith("/thumb/"):
            pid = os.path.basename(u.path).split("?")[0]
            it = next((x for x in BOOKMARKS if str(x["id"])==pid), None)
            if not it:
                return self.send_error(404)
            # 解析 lang 参数(demo 模式时前端用 ?lang= 切换占位文字语言, user 模式忽略)
            lang = urllib.parse.parse_qs(u.query).get("lang", ["zh"])[0]
            if lang not in ("en", "zh"):
                lang = "zh"
            local = thumb_for(it, lang)
            if not local:
                return self.send_error(404)
            with open(local, "rb") as f:
                body = f.read()
            ctype = "image/svg+xml" if local.endswith(".svg") else "image/jpeg"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "max-age=86400")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/asset-pos":
            d = {}
            if os.path.exists(POS_FILE):
                try: d = json.load(open(POS_FILE, encoding="utf-8"))
                except Exception: pass
            self.send_json(200, d)
        elif u.path.startswith("/assets/"):
            # 自定义横幅/头像: /assets/banner 或 /assets/avatar
            kind = u.path[len("/assets/"):].split("?")[0]
            if kind not in ("banner", "avatar"):
                return self.send_error(404)
            local = asset_path(kind)
            if not local:
                return self.send_error(404)
            with open(local, "rb") as f:
                body = f.read()
            ext = os.path.splitext(local)[1].lower()
            ct = {"png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/plugins":
            # 返回插件列表(供前端渲染按钮和设置页)
            self.send_json(200, {"plugins": PLUGIN_LIST})
        elif u.path == "/api/plugins/detect":
            # 自动探测URL的JSON结构
            url = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("url", [""])[0].strip()
            if not url:
                return self.send_json(400, {"error": "缺少url参数 | Missing url parameter"})
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "PixivFavSearch/1.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    raw = r.read().decode("utf-8", "ignore")
                data = json.loads(raw)
                if not isinstance(data, list):
                    if isinstance(data, dict):
                        found = False
                        for k, v in data.items():
                            if isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                                data = v
                                found = True
                                break
                        if not found:
                            return self.send_json(400, {"error": "数据不是列表格式 | Data is not a list"})
                    else:
                        return self.send_json(400, {"error": "数据不是列表格式 | Data is not a list"})
                
                sample = data[:10]
                detected = _detect_fields(sample)
                
                # 采样前3条供预览
                preview = []
                for item in sample[:3]:
                    if isinstance(item, dict):
                        preview.append({k: str(v)[:100] for k, v in item.items() if not k.startswith("_")})
                
                self.send_json(200, {
                    "ok": True,
                    "total": len(data),
                    "sample_fields": list(set(k for k in sample[0].keys() if not k.startswith("_"))) if sample else [],
                    "detected": {k: {"field": v[0], "confidence": v[1]} for k, v in detected.items()},
                    "preview": preview,
                })
            except Exception as e:
                self.send_json(400, {"error": f"探测失败: {repr(e)[:150]} | Detection failed: {repr(e)[:150]}"})
        elif u.path == "/api/plugins/reload":
            # 重新加载所有插件数据
            load_plugins()
            self.send_json(200, {"ok": True, "counts": {k: len(v) for k, v in PLUGIN_DATA.items()}})
        elif u.path == "/api/plugins/market":
            # 获取插件市场列表
            url = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("url", [None])[0]
            result = fetch_market(url)
            self.send_json(200, result)
        elif u.path == "/api/plugins/info":
            # 返回已安装插件的详细信息
            pid = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("id", [""])[0]
            plugin = next((p for p in PLUGIN_LIST if p["id"] == pid), None)
            if not plugin:
                return self.send_json(404, {"error": "插件不存在"})
            count = len(PLUGIN_DATA.get(pid, []))
            self.send_json(200, {"plugin": plugin, "count": count})
        else:
            self.send_error(404)

    def do_POST(self):
        try:
            self._handle_post()
        except Exception:
            try:
                self._deny(400, "Bad Request (pix_search_server)")
            except Exception:
                pass

    def _handle_post(self):
        if not (self._ip_ok() and self._host_ok()):
            self._deny()
            return
        if not self._origin_ok():
            self._deny()
            return
        if not self._auth_ok():
            self._deny()
            return
        if not self._body_ok():
            self._deny(413, "Payload Too Large (pix_search_server)")
            return
        if not self._rate_ok():
            self._deny(429, "Too Many Requests (pix_search_server)")
            return
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/import":
            # 从 Pixiv 抓取最新收藏(CDP)。启动导入线程, 返回是否已启动
            log_info("POST /api/import 触发导入 | POST /api/import triggered")
            started = start_import()
            self.send_json(200, {"ok": True, "started": started})
            return
        m = _re.match(r"^/api/asset/(banner|avatar)$", u.path)
        if m:
            kind = m.group(1)
            log_debug(f"POST /api/asset/{kind} 上传封面 | POST /api/asset/{kind} upload cover")
            ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = ASSET_EXT.get(ct)
            if not ext:
                return self.send_json(400, {"error": "不支持的图片类型: " + (ct or "空")})
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n > 0 else b""
            if len(body) < 100:
                return self.send_json(400, {"error": "图片数据为空或过小"})
            # 删掉旧的同名资源(不同扩展名)
            for f in os.listdir(ASSETS):
                if f.startswith(kind + "."):
                    try: os.remove(os.path.join(ASSETS, f))
                    except OSError: pass
            with open(os.path.join(ASSETS, kind + ext), "wb") as f:
                f.write(body)
            return self.send_json(200, {"ok": True, "kind": kind, "ext": ext})
        if u.path == "/api/asset-pos":
            # 保存横幅/头像的显示位置 {banner:{x,y,s}, avatar:{x,y,s}}
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            old = {}
            if os.path.exists(POS_FILE):
                try: old = json.load(open(POS_FILE, encoding="utf-8"))
                except Exception: pass
            for k in ("banner", "avatar"):
                if k in data and isinstance(data[k], dict):
                    old[k] = {kk: float(data[k].get(kk, 0)) for kk in ("x", "y", "s")}
            with open(POS_FILE, "w", encoding="utf-8") as f:
                json.dump(old, f, ensure_ascii=False)
            return self.send_json(200, {"ok": True})
        if u.path == "/api/plugins/save":
            # 保存插件配置(开关/新增/删除)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8") or "{}"
                data = json.loads(body)
            except Exception:
                return self.send_json(400, {"error": "JSON解析失败 | JSON parse error"})
            
            action = data.get("action", "")
            
            if action == "toggle":
                # 开关插件
                pid = data.get("id", "")
                enabled = data.get("enabled", True)
                for p in PLUGIN_LIST:
                    if p["id"] == pid:
                        p["enabled"] = enabled
                        break
                save_plugin_config(PLUGIN_LIST)
                load_plugins()
                return self.send_json(200, {"ok": True})
            
            elif action == "add":
                # 添加自定义数据源
                name = data.get("name", "").strip()
                url = data.get("url", "").strip()
                mapping = data.get("mapping", {})
                icon = data.get("icon", "🔗")
                
                if not name or not url:
                    return self.send_json(400, {"error": "缺少名称或URL | Missing name or url"})
                
                # 生成唯一ID
                pid = "custom_" + _hashlib.md5(url.encode()).hexdigest()[:8]
                
                new_plugin = {
                    "id": pid,
                    "name": name,
                    "type": "custom",
                    "enabled": True,
                    "icon": icon,
                    "config": {"url": url},
                    "mapping": mapping,
                }
                
                PLUGIN_LIST.append(new_plugin)
                save_plugin_config(PLUGIN_LIST)
                
                # 尝试加载
                result = _load_plugin(new_plugin)
                if "error" in result:
                    return self.send_json(200, {"ok": True, "plugin": new_plugin, "load_error": result["error"]})
                
                return self.send_json(200, {"ok": True, "plugin": new_plugin, "count": len(PLUGIN_DATA.get(pid, []))})
            
            elif action == "delete":
                pid = data.get("id", "")
                PLUGIN_LIST = [p for p in PLUGIN_LIST if p["id"] != pid]
                PLUGIN_DATA.pop(pid, None)
                save_plugin_config(PLUGIN_LIST)
                return self.send_json(200, {"ok": True})
            
            elif action == "update_mapping":
                pid = data.get("id", "")
                mapping = data.get("mapping", {})
                for p in PLUGIN_LIST:
                    if p["id"] == pid:
                        p["mapping"] = mapping
                        break
                save_plugin_config(PLUGIN_LIST)
                load_plugins()
                return self.send_json(200, {"ok": True})
            
            return self.send_json(400, {"error": "未知操作 | Unknown action"})
        if u.path == "/api/plugins/install":
            # 安装插件（从 URL）
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8") or "{}"
                data = json.loads(body)
            except Exception:
                return self.send_json(400, {"error": "JSON解析失败"})
            url = data.get("url", "").strip()
            if not url:
                return self.send_json(400, {"error": "缺少 url 参数"})
            result = install_plugin_from_url(url)
            if "error" in result:
                self.send_json(400, result)
            else:
                self.send_json(200, result)
        if u.path == "/api/plugins/uninstall":
            # 卸载插件
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8") or "{}"
                data = json.loads(body)
            except Exception:
                return self.send_json(400, {"error": "JSON解析失败"})
            pid = data.get("id", "").strip()
            if not pid:
                return self.send_json(400, {"error": "缺少 id 参数"})
            result = uninstall_plugin(pid)
            if "error" in result:
                self.send_json(400, result)
            else:
                self.send_json(200, result)
        if u.path == "/api/plugins/scan":
            # 扫描 plugins 文件夹
            scan_plugins_dir()
            self.send_json(200, {"ok": True})
        if u.path == "/api/plugins/upload":
            # 上传 .plug 文件（拖拽安装）
            ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ct != "application/octet-stream":
                return self.send_json(400, {"error": "只接受 .plug 文件"})
            n = int(self.headers.get("Content-Length") or 0)
            if n == 0 or n > 50 * 1024 * 1024:
                return self.send_json(400, {"error": "文件过大或为空"})
            body = self.rfile.read(n)
            import tempfile, zipfile
            tmp = tempfile.NamedTemporaryFile(suffix='.plug', delete=False)
            try:
                tmp.write(body)
                tmp.close()
                result = _install_plugin_from_zip(tmp.name)
                if "error" in result:
                    self.send_json(400, result)
                else:
                    self.send_json(200, result)
            except Exception as e:
                self.send_json(500, {"error": repr(e)[:200]})
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
        return self.send_error(404)

    def version_string(self):
        # 隐藏 Python/版本号, 不暴露服务器实现细节
        return ""

    def _sec_headers(self, csp=True):
        """通用安全响应头: nosniff + 防缓存 + 引用策略 + 框架隔离"""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")
        if csp:
            # 锁死可加载来源: 仅自身 + E站缩略图直链; 禁 iframe 嵌套
            self.send_header("Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' https://ehgt.org data:; "
                "media-src 'self' data:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")

    def send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        if getattr(self, "_set_cookie", False):
            # 手机等非本机设备首次带 key 访问时种下会话 Cookie, 之后免 key
            # 注意: 不设 Secure(服务是HTTP, 设了手机浏览器会拒收Cookie导致登录失效)
            self.send_header("Set-Cookie", f"pixkey={ACCESS_KEY}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
            # 登记 token→IP 绑定(防嗅探重放)
            with _TOKEN_IP_LOCK:
                _TOKEN_IP[ACCESS_KEY] = self.client_address[0]
        self._sec_headers()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._sec_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INDEX = r"""<!doctype html><html lang=zh><meta charset=utf-8><title>PixivFavSearch</title>
<style>
 :root{
  --bg:#F2F2F7;--card:#FFFFFF;--text:#1C1C1E;--sub:#8E8E93;--accent:#ef9eff;--accent-ink:#2b0030;
  --field-bg:#FFFFFF;--field-border:#E5E5EA;--topbar:rgba(242,242,247,.82);
  --shadow:0 2px 10px rgba(0,0,0,.05);--shadow-hover:0 12px 28px rgba(0,0,0,.13);
 }
 @media (prefers-color-scheme: dark){
  :root{
   --bg:#000000;--card:#1C1C1E;--text:#F2F2F7;--sub:#98989F;--accent:#ef9eff;--accent-ink:#2b0030;
   --field-bg:#2C2C2E;--field-border:#38383A;--topbar:rgba(0,0,0,.72);
   --shadow:0 2px 10px rgba(0,0,0,.45);--shadow-hover:0 12px 30px rgba(0,0,0,.65);
  }
 }
 body{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);margin:0;padding:24px 20px 60px;transition:background .3s,color .3s}
 .topbar{position:sticky;top:0;z-index:10;background:var(--topbar);backdrop-filter:blur(16px) saturate(180%);-webkit-backdrop-filter:blur(16px) saturate(180%);margin:-24px -20px 0;padding:12px 20px 10px}
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
 a{text-decoration:none;color:inherit}
 /* 悬浮回主页按钮(低调) */
#home-btn{position:fixed;bottom:18px;right:18px;z-index:9999;width:32px;height:32px;border-radius:50%;background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.1);color:var(--sub);font-size:15px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .2s;box-shadow:none;opacity:.4;backdrop-filter:blur(4px)}
#home-btn:hover{opacity:.9;color:#ef9eff;border-color:rgba(239,158,255,.5)}
#home-btn .ttip{position:absolute;right:40px;white-space:nowrap;background:rgba(0,0,0,.8);padding:3px 8px;border-radius:6px;font-size:11px;border:1px solid rgba(255,255,255,.1);opacity:0;pointer-events:none;transition:opacity .18s;color:var(--fg)}
#home-btn:hover .ttip{opacity:1}
.empty{color:var(--sub);padding:60px 0;text-align:center;font-size:14px;animation:popIn .4s cubic-bezier(.34,1.56,.64,1) both}
 @keyframes popIn{0%{opacity:0;transform:translateY(12px)}60%{opacity:1;transform:translateY(-4px)}100%{opacity:1;transform:translateY(0)}}
 ::-webkit-scrollbar{width:10px}::-webkit-scrollbar-thumb{background:var(--sub);border-radius:6px;border:2px solid var(--bg)}

/* -- 数据源设置按钮 -- */
.settings-btn{border:none;cursor:pointer;font-size:12px;font-weight:700;color:rgba(255,255,255,.75);background:transparent;padding:6px 16px;border-radius:18px;transition:background .2s,color .2s,transform .18s cubic-bezier(.34,1.56,.64,1)}
.settings-btn:hover{color:#fff;transform:scale(1.05);background:rgba(255,255,255,.15)}
.settings-btn:active{transform:scale(.9)}
/* -- 设置弹窗 -- */
.settings-modal{position:fixed;inset:0;z-index:999;background:rgba(0,0,0,.5);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:20px}
.settings-modal.open{display:flex}
.settings-box{background:var(--card);border-radius:18px;padding:0;width:min(92vw,560px);max-height:80vh;box-shadow:0 20px 60px rgba(0,0,0,.45);animation:popIn .3s cubic-bezier(.34,1.56,.64,1) both;display:flex;flex-direction:column;overflow:hidden}
.settings-header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--field-border)}
.settings-title{font-size:16px;font-weight:700}
.settings-close{width:32px;height:32px;border:none;background:var(--field-bg);border-radius:50%;cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center;transition:background .2s}
.settings-close:hover{background:var(--field-border)}
.settings-body{padding:16px 20px;overflow-y:auto;flex:1}
.plugin-list{display:flex;flex-direction:column;gap:8px}
.plugin-item{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;background:var(--field-bg);border:1px solid var(--field-border);transition:border-color .2s}
.plugin-item:hover{border-color:var(--accent)}
.plugin-item.disabled{opacity:.5}
.plugin-item-icon{font-size:22px;width:36px;text-align:center;flex-shrink:0}
.plugin-item-info{flex:1;min-width:0}
.plugin-item-name{font-size:14px;font-weight:600;display:flex;align-items:center;gap:6px}
.plugin-item-badge{font-size:10px;padding:2px 8px;border-radius:10px;background:var(--accent);color:var(--accent-ink);font-weight:700}
.plugin-item-badge.builtin{background:var(--field-border);color:var(--text)}
.plugin-item-count{font-size:11px;color:var(--sub);margin-top:2px}
.plugin-item-actions{display:flex;align-items:center;gap:8px}
.plugin-toggle{width:44px;height:24px;border-radius:12px;border:none;cursor:pointer;position:relative;background:var(--field-border);transition:background .2s;flex-shrink:0}
.plugin-toggle.on{background:var(--accent)}
.plugin-toggle::after{content:'';position:absolute;width:18px;height:18px;border-radius:50%;background:#fff;top:3px;left:3px;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.2)}
.plugin-toggle.on::after{transform:translateX(20px)}
.plugin-delete-btn{width:28px;height:28px;border:none;background:transparent;border-radius:50%;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:background .2s,color .2s}
.plugin-delete-btn:hover{background:rgba(255,69,58,.15);color:#FF453A}
.plugin-add{margin-top:12px;padding-top:12px;border-top:1px solid var(--field-border)}
.plugin-add-btn{width:100%;padding:12px;border:1px dashed var(--field-border);border-radius:12px;background:transparent;cursor:pointer;font-size:14px;font-weight:600;color:var(--sub);transition:border-color .2s,color .2s}
.plugin-add-btn:hover{border-color:var(--accent);color:var(--accent)}
/* -- 向导弹窗 -- */
.wizard-modal{position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.5);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:20px}
.wizard-modal.open{display:flex}
.wizard-box{background:var(--card);border-radius:18px;padding:0;width:min(92vw,600px);max-height:85vh;box-shadow:0 20px 60px rgba(0,0,0,.45);animation:popIn .3s cubic-bezier(.34,1.56,.64,1) both;display:flex;flex-direction:column;overflow:hidden}
.wizard-header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--field-border)}
.wizard-title{font-size:16px;font-weight:700}
.wizard-body{padding:20px;overflow-y:auto;flex:1}
.wizard-step{display:none}
.wizard-step.active{display:block}
.wizard-step-title{font-size:18px;font-weight:700;margin-bottom:4px}
.wizard-step-sub{font-size:13px;color:var(--sub);margin-bottom:16px}
.wizard-url-input{width:100%;padding:12px 16px;border-radius:12px;border:1px solid var(--field-border);background:var(--field-bg);color:var(--text);font-size:14px;box-sizing:border-box;font-family:Consolas,monospace}
.wizard-url-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%,transparent)}
.wizard-error{margin-top:12px;padding:12px 16px;border-radius:12px;background:rgba(255,69,58,.1);border:1px solid rgba(255,69,58,.3);color:#FF453A;font-size:13px;display:none}
.wizard-error.show{display:block}
.wizard-error-title{font-weight:700;margin-bottom:4px}
.wizard-error-msg{font-size:12px;line-height:1.5}
.wizard-error-actions{margin-top:8px;display:flex;gap:8px}
.wizard-hint{margin-top:12px;padding:12px 16px;border-radius:12px;background:color-mix(in srgb,var(--accent) 10%,transparent);border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);font-size:12px;line-height:1.6}
.wizard-hint-title{font-weight:700;margin-bottom:4px;color:var(--accent)}
.wizard-mapping{margin-top:16px}
.wizard-mapping-title{font-size:14px;font-weight:700;margin-bottom:10px}
.wizard-mapping-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;padding:8px 12px;background:var(--field-bg);border-radius:8px}
.wizard-mapping-field{font-size:13px;font-weight:600;min-width:80px;display:flex;align-items:center;gap:6px}
.wizard-mapping-arrow{color:var(--sub);font-size:12px}
.wizard-mapping-select{flex:1;padding:6px 10px;border-radius:8px;border:1px solid var(--field-border);background:var(--card);color:var(--text);font-size:13px}
.wizard-mapping-select:focus{outline:none;border-color:var(--accent)}
.wizard-mapping-conf{font-size:11px;padding:2px 8px;border-radius:10px;font-weight:600;flex-shrink:0}
.wizard-mapping-conf.high{background:rgba(52,199,89,.15);color:#34C759}
.wizard-mapping-conf.mid{background:rgba(255,159,10,.15);color:#FF9F0A}
.wizard-mapping-conf.low{background:rgba(255,69,58,.15);color:#FF453A}
.wizard-preview{margin-top:16px}
.wizard-preview-title{font-size:14px;font-weight:700;margin-bottom:10px}
.wizard-preview-cards{display:flex;gap:10px;overflow-x:auto;padding-bottom:8px}
.wizard-preview-card{min-width:120px;background:var(--field-bg);border-radius:10px;overflow:hidden;border:1px solid var(--field-border)}
.wizard-preview-card img{width:100%;height:100px;object-fit:cover;background:var(--card)}
.wizard-preview-card .ttl{padding:6px 8px;font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.wizard-preview-card .au{padding:0 8px 6px;font-size:10px;color:var(--sub)}
.wizard-footer{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-top:1px solid var(--field-border)}
.wizard-footer-left{display:flex;gap:8px}
.wizard-footer-right{display:flex;gap:8px}
.wizard-btn{padding:10px 20px;border-radius:12px;border:none;font-size:14px;font-weight:700;cursor:pointer;transition:transform .18s cubic-bezier(.34,1.56,.64,1)}
.wizard-btn:hover{transform:scale(1.04)}
.wizard-btn:active{transform:scale(.93)}
.wizard-btn.primary{background:var(--accent);color:var(--accent-ink)}
.wizard-btn.secondary{background:var(--field-bg);color:var(--text);border:1px solid var(--field-border)}
.wizard-btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.wizard-loading{text-align:center;padding:40px 0}
.wizard-loading-spinner{width:40px;height:40px;border:3px solid var(--field-border);border-top-color:var(--accent);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}
@keyframes spin{to{transform:rotate(360deg)}}
.wizard-loading-text{font-size:13px;color:var(--sub)}

/* -- 插件市场弹窗 -- */
.market-modal{position:fixed;inset:0;z-index:1001;background:rgba(0,0,0,.5);backdrop-filter:blur(6px);display:none;align-items:center;justify-content:center;padding:20px}
.market-modal.open{display:flex}
.market-box{background:var(--card);border-radius:18px;padding:0;width:min(92vw,640px);max-height:85vh;box-shadow:0 20px 60px rgba(0,0,0,.45);animation:popIn .3s cubic-bezier(.34,1.56,.64,1) both;display:flex;flex-direction:column;overflow:hidden}
.market-header{display:flex;align-items:center;justify-content:space-between;padding:18px 20px;border-bottom:1px solid var(--field-border)}
.market-title{font-size:16px;font-weight:700}
.market-body{padding:16px 20px;overflow-y:auto;flex:1}
.market-url-row{display:flex;gap:8px;margin-bottom:16px}
.market-url-input{flex:1;padding:10px 14px;border-radius:10px;border:1px solid var(--field-border);background:var(--field-bg);color:var(--text);font-size:13px;font-family:Consolas,monospace}
.market-url-input:focus{outline:none;border-color:var(--accent)}
.market-load-btn{padding:10px 16px;border-radius:10px;border:none;background:var(--accent);color:var(--accent-ink);font-size:13px;font-weight:700;cursor:pointer;white-space:nowrap}
.market-list{display:flex;flex-direction:column;gap:8px}
.market-item{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:12px;background:var(--field-bg);border:1px solid var(--field-border)}
.market-item-icon{font-size:28px;width:44px;text-align:center;flex-shrink:0}
.market-item-info{flex:1;min-width:0}
.market-item-name{font-size:14px;font-weight:600}
.market-item-desc{font-size:11px;color:var(--sub);margin-top:2px;line-height:1.4}
.market-item-actions{display:flex;align-items:center;gap:8px}
.market-install-btn{padding:8px 16px;border-radius:10px;border:none;background:var(--accent);color:var(--accent-ink);font-size:13px;font-weight:700;cursor:pointer}
.market-install-btn:disabled{opacity:.5;cursor:not-allowed}
.market-installed{font-size:11px;color:#34C759;font-weight:600}
.market-empty{color:var(--sub);text-align:center;padding:30px 0;font-size:13px}
/* -- 拖拽安装覆盖层 -- */
.drop-overlay{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);display:none;align-items:center;justify-content:center;flex-direction:column;gap:16px}
.drop-overlay.active{display:flex}
.drop-overlay-box{border:3px dashed rgba(255,255,255,.5);border-radius:24px;padding:60px 80px;text-align:center;color:#fff;font-size:18px;font-weight:700;background:rgba(255,255,255,.05)}
.drop-overlay-icon{font-size:48px;margin-bottom:12px}
</style>
<header class=topbar>
 <div class=banner id=banner>
  <img id=banner-img src=/assets/banner alt='' onerror="this.style.display='none'">
  <div class=banner-shade></div>
  <div class=banner-mark><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z'/></svg><span id=banner-mark-text data-l data-zh="Pixiv 书签搜索" data-en="PixivFavSearch">Pixiv 书签搜索</span></div>
  <div class=mode-switch>
   <button class="mode-btn active" id=btn-pixiv onclick="switchMode('pixiv')">📚 Pixiv</button>
   <button class="lang-btn" id=btn-lang onclick="toggleLang()">中 / EN</button>
   <button class="settings-btn" id=btn-settings onclick="openSettings()" data-l data-zh="⚙️ 数据源" data-en="⚙️ Sources">⚙️ 数据源</button>
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

<div id=settings-modal class=settings-modal>
 <div class=settings-box>
  <div class=settings-header>
   <div class=settings-title data-l data-zh="⚙️ 数据源管理" data-en="⚙️ Data Sources">⚙️ 数据源管理</div>
   <button class=settings-close onclick=closeSettings()>✕</button>
  </div>
  <div class=settings-body>
   <div id=plugin-list class=plugin-list></div>
   <div class=plugin-add>
    <button class=plugin-add-btn onclick="startAddPlugin()" data-l data-zh="➕ 添加自定义数据源" data-en="➕ Add Custom Source">➕ 添加自定义数据源</button>
    <button class=plugin-add-btn onclick="openMarket()" style="margin-top:8px" data-l data-zh="🛒 获取更多数据源" data-en="🛒 Get More Sources">🛒 获取更多数据源</button>
   </div>
  </div>
 </div>
</div>
<div id=wizard-modal class=wizard-modal>
 <div class=wizard-box>
  <div class=wizard-header>
   <div class=wizard-title id=wizard-title data-l data-zh="添加数据源" data-en="Add Data Source">添加数据源</div>
   <button class=settings-close onclick=closeWizard()>✕</button>
  </div>
  <div class=wizard-body id=wizard-body></div>
 </div>
</div>
</header>

<div id=market-modal class=market-modal>
 <div class=market-box>
  <div class=market-header>
   <div class=market-title data-l data-zh="🛒 插件市场" data-en="🛒 Plugin Market">🛒 插件市场</div>
   <button class=settings-close onclick=closeMarket()>✕</button>
  </div>
  <div class=market-body>
   <div class=market-url-row>
    <input class=market-url-input id=market-url placeholder="市场链接 (默认官方)" onkeydown="if(event.key==='Enter')loadMarket()">
    <button class=market-load-btn onclick="loadMarket()" data-l data-zh="加载" data-en="Load">加载</button>
   </div>
   <div id=market-list class=market-list></div>
  </div>
 </div>
</div>
<div id=drop-overlay class=drop-overlay>
 <div class=drop-overlay-box>
  <div class=drop-overlay-icon>📦</div>
  <div data-l data-zh="松开鼠标安装插件" data-en="Release to install plugin">松开鼠标安装插件</div>
 </div>
</div>
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
<button id=home-btn title="回到本站主页" data-l-t data-zh-t="回到本站主页" data-en-t="Back to homepage" onclick="location.href='/'"><svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' stroke-linejoin='round'><path d='M3 10.5L12 3l9 7.5'/><path d='M5 9.5V21h14V9.5'/></svg><span class=ttip data-l data-zh="🏠 回到本站" data-en="🏠 Home">🏠 回到本站</span></button>
<script>
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
   document.getElementById('crop-modal').style.display='flex'; // 先显示弹窗,再量 stage 尺寸
   const stage=document.getElementById('crop-stage'),ci=document.getElementById('crop-img');
   const stw=stage.clientWidth,sth=stage.clientHeight;
   const r=Math.min(stw/crop.natW,sth/crop.natH);
   crop.bw=crop.natW*r;crop.bh=crop.natH*r;crop.tx=0;crop.ty=0;crop.s=1;
   // 裁剪框比例:横幅按实际显示比例(容器宽/150),头像 1:1
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
  // 保证裁剪框始终在图片范围内(不露黑边)
  // 图片中心相对 stage 中心的偏移 tx,须满足:图片左右缘包住裁剪框左右缘
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
  // 图片实际显示区域(左上角)
  const imgW=crop.bw*crop.s,imgH=crop.bh*crop.s;
  const imgLeft=stw/2+crop.tx-imgW/2,imgTop=sth/2+crop.ty-imgH/2;
  const frLeft=(stw-crop.fw)/2,frTop=(sth-crop.fh)/2;
  // 相对图片的比例 → 原图像素
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
  const re=new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi');
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
 if(DATASRC==='demo'){
  if(_db)_db.style.display='block'; // 底部固定提示条: 仅 demo 模式显示
  if(!location.hash){ go(); } // 自动搜一次, 展示全部示例
 }else if(_db){
  _db.style.display='none'; // user/no-data 模式隐藏
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
    im.src='/thumb/'+base+'?lang='+LANG; // 不同 lang 不同 URL, 浏览器缓存天然不串
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
 // 搜索前先存档(仅当和栈顶不同才存,避免重复搜索塞满栈)
 const cur=snapshot();
 const top=undoStack[undoStack.length-1];
 if(!top||top.q!==cur.q||top.tag!==cur.tag||top.colt!==cur.colt||top.mode!==cur.mode){
  undoStack.push(cur);if(undoStack.length>50)undoStack.shift();
  markHistory(); // 多压一个历史项,让 Alt+←/鼠标后退 能先触发 popstate 事件
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
   // demo 模式: 纯展示占位卡片 — 无链接、无打开按钮、标题/作者/标签用占位文案
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
   <a class=go href="https://www.pixiv.net/artworks/${it.id}">🔗 ${LANG==='zh'?'打开 Pixiv':'Open Pixiv'}</a>
 </div>`;
 }).join('');
 // 把搜索条件写进 URL(#参数),从外部页面按后退键回来时能自动恢复结果
 history.replaceState(history.state,'','#'+new URLSearchParams({mode:MODE,q:q,tag:tag,colt:colt}).toString());
}
// Ctrl+Z 撤销(捕获阶段,拦截输入框原生撤销)
document.addEventListener('keydown',function(e){
 if((e.ctrlKey||e.metaKey)&&(e.key==='z'||e.key==='Z')){e.preventDefault();e.stopPropagation();undoSearch();}
},true);
// 导入/更新收藏(CDP 抓取最新收藏)
async function doImport(){
 const btn=document.getElementById('btn-import');
 const hint=document.getElementById('hint');
 if(btn.classList.contains('loading'))return; // 已在导入中
 btn.classList.add('loading');btn.textContent=LANG==='zh'?'⏳ 导入中…':'⏳ Importing…';
 hint.textContent=LANG==='zh'?'正在连接浏览器抓取最新收藏, 请稍候…':'Connecting to browser to fetch latest bookmarks…';
 try{
  const r=await fetch('/api/import',{method:'POST'});
  const j=await r.json();
  if(!j.started){ hint.textContent=LANG==='zh'?'已有导入任务在运行, 请稍候…':'Import already running…'; btn.classList.remove('loading');btn.textContent=(LANG==='zh'?'📥 导入/更新收藏':'📥 Import / Update'); return; }
  // 轮询状态直到完成(最多 180s)
  for(let i=0;i<90;i++){
   await new Promise(res=>setTimeout(res,2000));
   const sr=await fetch('/api/import-status');
   const s=await sr.json();
   if(!s.running){
    hint.style.color=s.code===0?'#34C759':'#FF453A';
    hint.textContent=s.msg||(LANG==='zh'?'导入完成':'Done');
    btn.classList.remove('loading');btn.textContent=(LANG==='zh'?'📥 导入/更新收藏':'📥 Import / Update');
    if(s.code===0){ await go(); } // 刷新搜索结果(数据已热重载)
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

// ===== 插件系统前端 =====
let PLUGINS = [];  // 当前插件列表
let WIZARD_STATE = {step: 0, url: "", detected: null, mapping: {}, name: "", preview: []};

// 初始化:加载插件列表并渲染按钮
(async function(){
  try {
    const r = await fetch('/api/plugins');
    const d = await r.json();
    PLUGINS = d.plugins || [];
    renderPluginButtons();
  } catch(e) {}
})();

function renderPluginButtons(){
  const container = document.querySelector('.mode-switch');
  if(!container) return;
  
  // 移除旧的插件按钮(保留pixiv和settings)
  container.querySelectorAll('.mode-btn:not(#btn-pixiv)').forEach(b => b.remove());
  
  // 在settings按钮前插入启用的插件按钮
  const settingsBtn = document.getElementById('btn-settings');
  
  PLUGINS.forEach(p => {
    if(!p.enabled) return;
    const btn = document.createElement('button');
    btn.className = 'mode-btn';
    btn.id = 'btn-' + p.id;
    btn.dataset.pid = p.id;
    btn.innerHTML = (p.icon || '📁') + ' ' + esc(p.name);
    btn.onclick = () => switchMode(p.id);
    container.insertBefore(btn, settingsBtn);
  });
  
  // 更新当前选中状态
  document.querySelectorAll('.mode-switch .mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.pid === MODE);
  });
}

function openSettings(){
  const modal = document.getElementById('settings-modal');
  modal.classList.add('open');
  renderPluginList();
}
function closeSettings(){
  document.getElementById('settings-modal').classList.remove('open');
}

function renderPluginList(){
  const container = document.getElementById('plugin-list');
  if(!container) return;
  
  container.innerHTML = PLUGINS.map(p => {
    const isBuiltin = p.type === 'builtin';
    return `<div class="plugin-item ${p.enabled ? '' : 'disabled'}">
      <div class="plugin-item-icon">${p.icon || '📁'}</div>
      <div class="plugin-item-info">
        <div class="plugin-item-name">${esc(p.name)} <span class="plugin-item-badge ${isBuiltin ? 'builtin' : ''}">${isBuiltin ? (LANG==='zh'?'内置':'Built-in') : (LANG==='zh'?'自定义':'Custom')}</span></div>
        <div class="plugin-item-count">${p.enabled ? (PLUGIN_DATA_COUNT[p.id] || '?') + (LANG==='zh'?' 条':' items') : (LANG==='zh'?'已禁用':'Disabled')}</div>
      </div>
      <div class="plugin-item-actions">
        <button class="plugin-toggle ${p.enabled ? 'on' : ''}" onclick="togglePlugin('${esc(p.id)}', ${!p.enabled})" title="${p.enabled ? (LANG==='zh'?'关闭':'Off') : (LANG==='zh'?'开启':'On')}"></button>
        ${!isBuiltin ? `<button class="plugin-delete-btn" onclick="deletePlugin('${esc(p.id)}')" title="${LANG==='zh'?'删除':'Delete'}">🗑</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

function togglePlugin(id, enabled){
  fetch('/api/plugins/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'toggle', id, enabled})
  }).then(r => r.json()).then(d => {
    if(d.ok){
      PLUGINS.forEach(p => { if(p.id === id) p.enabled = enabled; });
      renderPluginList();
      renderPluginButtons();
      // 如果当前模式被禁用,切回pixiv
      if(!enabled && MODE === id) switchMode('pixiv');
    }
  });
}

function deletePlugin(id){
  if(!confirm(LANG==='zh'?'确定删除此数据源?':'Delete this source?')) return;
  fetch('/api/plugins/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'delete', id})
  }).then(r => r.json()).then(d => {
    if(d.ok){
      PLUGINS = PLUGINS.filter(p => p.id !== id);
      renderPluginList();
      renderPluginButtons();
      if(MODE === id) switchMode('pixiv');
    }
  });
}


// ===== 插件市场 =====
let MARKET_CACHE = null;
let MARKET_URL_USED = '';

function openMarket(){
  document.getElementById('market-modal').classList.add('open');
  if(!MARKET_CACHE) loadMarket();
}
function closeMarket(){
  document.getElementById('market-modal').classList.remove('open');
}
async function loadMarket(){
  const urlInput = document.getElementById('market-url');
  const url = urlInput.value.trim() || '';
  const list = document.getElementById('market-list');
  list.innerHTML = '<div class=market-empty">加载中...</div>';
  try {
    const r = await fetch('/api/plugins/market' + (url ? '?url=' + encodeURIComponent(url) : ''));
    const d = await r.json();
    if(d.error){ list.innerHTML = '<div class="market-empty">❌ ' + esc(d.error) + '</div>'; return; }
    MARKET_CACHE = d.plugins || [];
    MARKET_URL_USED = d.url || '';
    renderMarket(d.plugins || []);
  } catch(e){
    list.innerHTML = '<div class="market-empty">❌ 请求失败: ' + esc(e.message) + '</div>';
  }
}
function renderMarket(plugins){
  const list = document.getElementById('market-list');
  if(!plugins.length){ list.innerHTML = '<div class="market-empty">暂无可安装的插件</div>'; return; }
  const installed = new Set(PLUGINS.map(p=>p.id));
  list.innerHTML = plugins.map(p => {
    const isInstalled = installed.has(p.id);
    return `<div class="market-item">
      <div class="market-item-icon">${esc(p.icon||'📦')}</div>
      <div class="market-item-info">
        <div class="market-item-name">${esc(p.name||p.id)}</div>
        <div class="market-item-desc">${esc(p.description||'')}</div>
      </div>
      <div class="market-item-actions">
        ${isInstalled ? '<span class="market-installed">✓ 已安装</span>' :
          '<button class="market-install-btn" onclick="installMarketPlugin(''+esc(p.id)+'',''+esc(p.download_url||'')+'')">安装</button>'}
      </div>
    </div>`;
  }).join('');
}
async function installMarketPlugin(pid, url){
  if(!url){ alert('该插件没有提供下载链接'); return; }
  try {
    const r = await fetch('/api/plugins/install', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({url})
    });
    const d = await r.json();
    if(d.error){ alert('安装失败: ' + d.error); return; }
    // 重新加载插件列表
    await loadPluginsList();
    closeMarket();
    alert('✅ ' + (d.name||pid) + ' 安装成功！');
  } catch(e){
    alert('安装失败: ' + e.message);
  }
}
async function loadPluginsList(){
  try {
    const r = await fetch('/api/plugins');
    const d = await r.json();
    PLUGINS = d.plugins || [];
    renderPluginButtons();
    renderPluginList && renderPluginList();
  } catch(e){}
}

// ===== 拖拽安装 =====
(function(){
  let dragCounter = 0;
  const overlay = document.getElementById('drop-overlay');
  document.addEventListener('dragenter', e => {
    e.preventDefault();
    dragCounter++;
    if(e.dataTransfer && e.dataTransfer.types.includes('Files')){
      overlay.classList.add('active');
    }
  });
  document.addEventListener('dragleave', e => {
    e.preventDefault();
    dragCounter = Math.max(0, dragCounter - 1);
    if(dragCounter === 0) overlay.classList.remove('active');
  });
  document.addEventListener('dragover', e => { e.preventDefault(); });
  document.addEventListener('drop', async e => {
    e.preventDefault();
    dragCounter = 0;
    overlay.classList.remove('active');
    const files = e.dataTransfer.files;
    if(!files.length) return;
    let installed = 0;
    let errors = [];
    for(const f of files){
      if(!f.name.endsWith('.plug')){ continue; }
      try {
        const buf = await f.arrayBuffer();
        const r = await fetch('/api/plugins/upload', {
          method:'POST',
          headers:{'Content-Type':'application/octet-stream', 'Content-Length': buf.byteLength.toString()},
          body: buf
        });
        const d = await r.json();
        if(d.error){ errors.push(f.name + ': ' + d.error); }
        else { installed++; }
      } catch(err){ errors.push(f.name + ': ' + err.message); }
    }
    if(installed > 0){
      await loadPluginsList();
      alert('✅ 已安装 ' + installed + ' 个插件！' + (errors.length ? '\n\n失败:\n' + errors.join('\n') : ''));
    } else if(errors.length){
      alert('❌ 安装失败:\n' + errors.join('\n'));
    }
  });
})();

// ===== 添加数据源向导 =====
function startAddPlugin(){
  closeSettings();
  WIZARD_STATE = {step: 1, url: '', detected: null, mapping: {}, name: '', preview: [], error: null};
  openWizard();
  renderWizardStep();
}

function openWizard(){
  document.getElementById('wizard-modal').classList.add('open');
}
function closeWizard(){
  document.getElementById('wizard-modal').classList.remove('open');
}

function renderWizardStep(){
  const body = document.getElementById('wizard-body');
  const title = document.getElementById('wizard-title');
  const state = WIZARD_STATE;
  
  if(state.step === 1){
    title.textContent = LANG==='zh' ? '第1步: 粘贴数据链接' : 'Step 1: Paste Data URL';
    body.innerHTML = `
      <div class="wizard-step active">
        <div class="wizard-step-title">${LANG==='zh' ? '📎 粘贴你的数据链接' : '📎 Paste Your Data URL'}</div>
        <div class="wizard-step-sub">${LANG==='zh' ? '把你的收藏文件链接粘贴到下面' : 'Paste the link to your collection file below'}</div>
        <input class="wizard-url-input" id="wizard-url" placeholder="${LANG==='zh' ? 'https://example.com/my_collection.json' : 'https://example.com/my_collection.json'}" value="${esc(state.url)}">
        <div class="wizard-error" id="wizard-error">
          <div class="wizard-error-title">${LANG==='zh' ? '❌ 添加失败' : '❌ Failed'}</div>
          <div class="wizard-error-msg" id="wizard-error-msg"></div>
          <div class="wizard-error-actions">
            <button class="wizard-btn secondary" onclick="document.getElementById('wizard-error').classList.remove('show')">${LANG==='zh' ? '关闭' : 'Close'}</button>
          </div>
        </div>
        <div class="wizard-hint">
          <div class="wizard-hint-title">${LANG==='zh' ? '💡 不知道链接是什么?' : "💡 Don't know what this is?"}</div>
          <div>${LANG==='zh' ? '方法1: 从网站导出收藏 → 上传到网盘 → 复制分享链接<br>方法2: 自己有JSON文件 → 上传到任何能生成直链的地方' : 'Method 1: Export from website → Upload to cloud storage → Copy share link<br>Method 2: Have a JSON file → Upload anywhere that gives a direct link'}</div>
        </div>
      </div>
    `;
    // 绑定回车事件
    setTimeout(() => {
      const inp = document.getElementById('wizard-url');
      if(inp) inp.addEventListener('keydown', e => { if(e.key === 'Enter') wizardStep1Next(); });
    }, 100);
  }
  else if(state.step === 2){
    title.textContent = LANG==='zh' ? '第2步: 确认数据预览' : 'Step 2: Confirm Preview';
    const det = state.detected || {};
    const mapping = state.mapping || {};
    const preview = state.preview || [];
    
    // 生成映射行
    const stdFields = [
      {key: 'title', label: LANG==='zh' ? '标题' : 'Title', icon: '📝'},
      {key: 'author', label: LANG==='zh' ? '作者' : 'Author', icon: '👤'},
      {key: 'thumb', label: LANG==='zh' ? '缩略图' : 'Thumbnail', icon: '🖼'},
      {key: 'tags', label: LANG==='zh' ? '标签' : 'Tags', icon: '🏷'},
      {key: 'url', label: LANG==='zh' ? '链接' : 'Link', icon: '🔗'},
      {key: 'desc', label: LANG==='zh' ? '描述' : 'Description', icon: '📄'},
    ];
    
    const allFields = det.sample_fields || [];
    
    const mappingRows = stdFields.map(sf => {
      const detected = mapping[sf.key];
      const conf = detected ? detected.confidence : 0;
      const confClass = conf >= 85 ? 'high' : conf >= 60 ? 'mid' : 'low';
      const confLabel = conf >= 85 ? (LANG==='zh'?'高':'High') : conf >= 60 ? (LANG==='zh'?'中':'Mid') : (LANG==='zh'?'低':'Low');
      
      const options = ['<option value="">-- ' + (LANG==='zh'?'忽略':'Skip') + ' --</option>'];
      allFields.forEach(f => {
        const sel = detected && detected.field === f ? 'selected' : '';
        options.push(`<option value="${esc(f)}" ${sel}>${esc(f)}</option>`);
      });
      
      return `<div class="wizard-mapping-row">
        <div class="wizard-mapping-field">${sf.icon} ${sf.label}</div>
        <div class="wizard-mapping-arrow">→</div>
        <select class="wizard-mapping-select" data-field="${sf.key}" onchange="updateWizardMapping('${sf.key}', this.value)">${options.join('')}</select>
        <div class="wizard-mapping-conf ${confClass}">${conf > 0 ? confLabel : (LANG==='zh'?'?':'?')}</div>
      </div>`;
    }).join('');
    
    // 预览卡片
    const previewCards = preview.slice(0, 5).map(item => {
      const title = esc((item.title || item.name || item.label || '').toString().slice(0, 30));
      const author = esc((item.author || item.artist || item.user || '').toString().slice(0, 20));
      const thumb = item.thumb || item.image || item.cover || '';
      return `<div class="wizard-preview-card">
        ${thumb ? `<img src="${esc(thumb)}" onerror="this.style.visibility='hidden'">` : ''}
        <div class="ttl">${title || (LANG==='zh'?'标题':'Title')}</div>
        <div class="au">${author || (LANG==='zh'?'作者':'Author')}</div>
      </div>`;
    }).join('');
    
    body.innerHTML = `
      <div class="wizard-step active">
        <div class="wizard-step-title">${LANG==='zh' ? '👀 确认数据看起来对吗?' : '👀 Does the data look right?'}</div>
        <div class="wizard-step-sub">${LANG==='zh' ? `我们读取到了 ${det.total || '?'} 条数据` : `We found ${det.total || '?'} items`}</div>
        <div class="wizard-mapping">
          <div class="wizard-mapping-title">${LANG==='zh' ? '字段映射(自动识别,可手动调整)' : 'Field Mapping (auto-detected, adjustable)'}</div>
          ${mappingRows}
        </div>
        ${previewCards ? `<div class="wizard-preview">
          <div class="wizard-preview-title">${LANG==='zh' ? '数据预览(前5条)' : 'Preview (first 5)'}</div>
          <div class="wizard-preview-cards">${previewCards}</div>
        </div>` : ''}
      </div>
    `;
  }
  else if(state.step === 3){
    title.textContent = LANG==='zh' ? '第3步: 完成' : 'Step 3: Done';
    body.innerHTML = `
      <div class="wizard-step active" style="text-align:center;padding:20px 0">
        <div style="font-size:48px;margin-bottom:12px">🎉</div>
        <div class="wizard-step-title">${LANG==='zh' ? '数据源添加成功!' : 'Data Source Added!'}</div>
        <div class="wizard-step-sub">${LANG==='zh' ? `"${esc(state.name)}" 已添加到数据源列表` : `"${esc(state.name)}" has been added`}</div>
        <div style="margin-top:16px;color:var(--sub);font-size:13px">${LANG==='zh' ? '现在你可以在搜索页看到新按钮了' : 'You can now see the new button on the search page'}</div>
      </div>
    `;
  }
}

function wizardStep1Next(){
  const urlInput = document.getElementById('wizard-url');
  const url = urlInput.value.trim();
  if(!url){
    showWizardError(LANG==='zh' ? '请输入链接' : 'Please enter a URL');
    return;
  }
  
  // 显示加载状态
  const body = document.getElementById('wizard-body');
  body.innerHTML = `<div class="wizard-loading">
    <div class="wizard-loading-spinner"></div>
    <div class="wizard-loading-text">${LANG==='zh' ? '正在读取和分析数据...' : 'Reading and analyzing data...'}</div>
  </div>`;
  
  fetch('/api/plugins/detect?url=' + encodeURIComponent(url))
    .then(r => r.json())
    .then(d => {
      if(d.error){
        showWizardError(d.error);
        return;
      }
      WIZARD_STATE.url = url;
      WIZARD_STATE.detected = d;
      WIZARD_STATE.preview = d.preview || [];
      WIZARD_STATE.mapping = {};
      
      // 自动填充高置信度映射
      for(const [stdField, info] of Object.entries(d.detected || {})){
        if(info.confidence >= 60){
          WIZARD_STATE.mapping[stdField] = info;
        }
      }
      
      WIZARD_STATE.step = 2;
      renderWizardStep();
    })
    .catch(e => {
      showWizardError((LANG==='zh' ? '请求失败: ' : 'Request failed: ') + e.message);
    });
}

function showWizardError(msg){
  const errDiv = document.getElementById('wizard-error');
  const errMsg = document.getElementById('wizard-error-msg');
  if(errDiv && errMsg){
    errMsg.textContent = msg;
    errDiv.classList.add('show');
  } else {
    // 如果错误div还没渲染,先回到step1
    WIZARD_STATE.step = 1;
    renderWizardStep();
    setTimeout(() => showWizardError(msg), 100);
  }
}

function updateWizardMapping(field, value){
  if(value){
    WIZARD_STATE.mapping[field] = {field: value, confidence: 99};
  } else {
    delete WIZARD_STATE.mapping[field];
  }
}

function wizardStep2Confirm(){
  // 收集映射
  const mapping = {};
  document.querySelectorAll('.wizard-mapping-select').forEach(sel => {
    const stdField = sel.dataset.field;
    const srcField = sel.value;
    if(srcField){
      mapping[stdField] = srcField;
    }
  });
  
  if(!mapping.title && !mapping.id){
    showWizardError(LANG==='zh' ? '至少需要映射标题或ID字段' : 'At least title or ID field must be mapped');
    return;
  }
  
  // 发送添加请求
  const body = document.getElementById('wizard-body');
  body.innerHTML = `<div class="wizard-loading">
    <div class="wizard-loading-spinner"></div>
    <div class="wizard-loading-text">${LANG==='zh' ? '正在保存...' : 'Saving...'}</div>
  </div>`;
  
  const name = WIZARD_STATE.name || WIZARD_STATE.url.split('/').pop().replace(/\\.json$/i, '') || 'Custom';
  
  fetch('/api/plugins/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({action: 'add', name, url: WIZARD_STATE.url, mapping, icon: '🔗'})
  }).then(r => r.json()).then(d => {
    if(d.ok){
      PLUGINS.push(d.plugin);
      WIZARD_STATE.step = 3;
      renderWizardStep();
      // 延迟更新按钮
      setTimeout(() => {
        renderPluginButtons();
        // 自动切到新数据源
        if(d.plugin && d.plugin.id) switchMode(d.plugin.id);
      }, 500);
    } else {
      showWizardError(d.error || (LANG==='zh' ? '保存失败' : 'Save failed'));
    }
  }).catch(e => {
    showWizardError((LANG==='zh' ? '请求失败: ' : 'Request failed: ') + e.message);
  });
}

// 向导底部按钮渲染
function renderWizardFooter(){
  const existing = document.querySelector('.wizard-footer');
  if(existing) existing.remove();
  
  const body = document.getElementById('wizard-body');
  const footer = document.createElement('div');
  footer.className = 'wizard-footer';
  
  const state = WIZARD_STATE;
  let html = '<div class="wizard-footer-left">';
  if(state.step > 1 && state.step < 3){
    html += `<button class="wizard-btn secondary" onclick="wizardGoBack()">${LANG==='zh' ? '← 上一步' : '← Back'}</button>`;
  }
  html += '</div><div class="wizard-footer-right">';
  
  if(state.step === 1){
    html += `<button class="wizard-btn secondary" onclick="closeWizard()">${LANG==='zh' ? '取消' : 'Cancel'}</button>`;
    html += `<button class="wizard-btn primary" onclick="wizardStep1Next()">${LANG==='zh' ? '下一步 →' : 'Next →'}</button>`;
  } else if(state.step === 2){
    html += `<button class="wizard-btn secondary" onclick="closeWizard()">${LANG==='zh' ? '取消' : 'Cancel'}</button>`;
    html += `<button class="wizard-btn primary" onclick="wizardStep2Confirm()">${LANG==='zh' ? '✅ 确认添加' : '✅ Confirm'}</button>`;
  } else if(state.step === 3){
    html += `<button class="wizard-btn primary" onclick="closeWizard()">${LANG==='zh' ? '完成' : 'Done'}</button>`;
  }
  
  html += '</div>';
  footer.innerHTML = html;
  body.appendChild(footer);
}

// 覆盖renderWizardStep以自动渲染底部按钮
const _origRenderWizardStep = renderWizardStep;
function renderWizardStep(){
  _origRenderWizardStep();
  renderWizardFooter();
}

function wizardGoBack(){
  if(WIZARD_STATE.step > 1){
    WIZARD_STATE.step--;
    renderWizardStep();
  }
}

// 修改switchModeNoGo以支持动态插件
const _origSwitchModeNoGo = switchModeNoGo;
function switchModeNoGo(m){
  if(MODE === m) return;
  MODE = m;
  
  // 更新按钮状态
  document.querySelectorAll('.mode-switch .mode-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.pid === m);
  });
  
  // 更新标题和副标题
  const plugin = PLUGINS.find(p => p.id === m);
  if(plugin){
    document.getElementById('banner-mark-text').textContent = plugin.name;
    document.getElementById('hd-title-text').textContent = plugin.name;
    document.getElementById('hd-sub-text').textContent = LANG==='zh' 
      ? `本地 · ${plugin.name} · 标题/标签/说明全字段搜索`
      : `Local · ${plugin.name} · Full-text search`;
  } else if(m === 'pixiv'){
    document.getElementById('banner-mark-text').textContent = 'PixivFavSearch';
    document.getElementById('hd-title-text').textContent = 'PixivFavSearch';
    document.getElementById('hd-sub-text').textContent = LANG==='zh'?'本地 · 全部收藏 · 标题/标签/简介全字段搜索 · 假名→罗马音跨语言':'Local · All bookmarks · Full-text title/tag/desc · kana→romaji';
  }
  
  // 显示/隐藏pixiv专属控件
  const isPixiv = m === 'pixiv';
  document.getElementById('dd-coltag').style.display = isPixiv ? '' : 'none';
  document.getElementById('dd-tag').style.display = isPixiv ? '' : 'none';
  document.getElementById('btn-import').style.display = isPixiv ? '' : 'none';
  
  const bar = document.querySelector('.bar');
  if(bar) bar.style.display = '';
  document.getElementById('q').placeholder = LANG==='zh'?'输入关键词...':'Search keyword...';
}

// 修改go()以支持插件搜索
const _origGo = go;
async function go(){
  const q = document.getElementById('q').value.trim();
  const g = document.getElementById('grid');
  const m = document.getElementById('meta');
  
  // 搜索前存档
  const cur = snapshot();
  const top = undoStack[undoStack.length-1];
  if(!top || top.q !== cur.q || top.tag !== cur.tag || top.colt !== cur.colt || top.mode !== cur.mode){
    undoStack.push(cur);
    if(undoStack.length > 50) undoStack.shift();
    markHistory();
  }
  
  g.innerHTML = '<div class=empty>搜索中…</div>';
  
  const tag = document.getElementById('tag').value;
  const colt = document.getElementById('coltag').value;
  
  const r = await fetch('/api/search?mode=' + MODE + '&q=' + encodeURIComponent(q) + '&tag=' + encodeURIComponent(tag) + '&coltag=' + encodeURIComponent(colt));
  const d = await r.json();
  
  m.textContent = (LANG==='zh' ? '共 ' : '') + d.total + (LANG==='zh' ? ' 条结果' : ' results');
  
  if(!d.items.length){
    g.innerHTML = '<div class=empty>' + (LANG==='zh'?'没有匹配的作品':'No matching works') + '</div>';
    return;
  }
  
  g.innerHTML = d.items.map(it => {

    const isDemo = DATASRC === 'demo' && MODE === 'pixiv';
    
    if(isDemo){
      return `<div class=card>
        <img loading=lazy decoding=async src="/thumb/${it.id}?lang=${LANG}" onerror="this.onerror=null;this.style.visibility='hidden'">
        <div class=tt>${LANG==='zh'?'标题':'Title'}</div>
        <div class=au>${LANG==='zh'?'作者':'Author'}</div>
        <div class=tg>🏷 ${LANG==='zh'?'示例标签':'Sample tag'}</div>
      </div>`;
    }
    
    const goUrl = it.url || '#';
    const goText = LANG==='zh' ? '🔗 打开' : '🔗 Open';
    // 处理 URL: 如果是 pximg 图片链接, 转为作品页面链接
    const pixivArtUrl = `https://www.pixiv.net/artworks/${it.id}`;
    const finalGoUrl = goUrl.includes('i.pximg.net') ? pixivArtUrl : goUrl;
    
    return `<div class=card>
      <a href="${esc(finalGoUrl)}" target="_blank">
        <img loading=lazy decoding=async src="/thumb/${it.id}?lang=${LANG}" onerror="this.onerror=null;this.style.visibility='hidden'">
        <div class=tt>${hlText(it.title, it.hl)}</div>
        <div class=au>${esc(it.author || '')}</div>
      </a>
      <div class=tg>🏷 ${esc(tagsOf(it))}</div>
      <a class=go href="${esc(goUrl)}" target="_blank">${goText}</a>
    </div>`;
  }).join('');
  
  history.replaceState(history.state, '', '#' + new URLSearchParams({mode: MODE, q, tag, colt}).toString());
}

// 插件数据计数(供设置页显示)
let PLUGIN_DATA_COUNT = {};
(async function(){
  try {
    const r = await fetch('/api/plugins/reload');
    const d = await r.json();
    if(d.counts) PLUGIN_DATA_COUNT = d.counts;
  } catch(e) {}
})();
</script>
"""

# --- 可复用的启动/停止函数(供 desktop_app 导入调用) ---
_server = None
def start_server(host="127.0.0.1", port=None, daemon=True):
    global _server
    if _server is not None and _server._serving_thread and _server._serving_thread.is_alive():
        return _server
    port = port or PORT
    # 提高连接排队容量: 默认 request_queue_size=5, 浏览器并发拉图/多设备访问时会拒连
    ThreadingHTTPServer.request_queue_size = 128
    # 线程上限: 防瞬时并发/慢速 DoS 耗尽线程
    import threading as _th
    _MAX_THREADS = 32
    _THREAD_SEM = _th.BoundedSemaphore(_MAX_THREADS)
    _orig_process = ThreadingHTTPServer.process_request
    def _limited_process(self, request, client_address):
        if not _THREAD_SEM.acquire(blocking=False):
            try: request.close()
            except Exception: pass
            return
        return _orig_process(self, request, client_address)
    ThreadingHTTPServer.process_request = _limited_process
    _orig_thread = ThreadingHTTPServer.process_request_thread
    def _release_thread(self, request, client_address):
        try:
            _orig_thread(self, request, client_address)
        finally:
            _THREAD_SEM.release()
    ThreadingHTTPServer.process_request_thread = _release_thread

    srv = ThreadingHTTPServer((host, port), H)
    _server = srv
    t = threading.Thread(target=srv.serve_forever, daemon=daemon)
    srv._serving_thread = t
    t.start()
    log_info(f"服务已启动 http://{host}:{port} | Server started at http://{host}:{port}")
    return srv

def stop_server():
    global _server
    if _server is not None:
        try: _server.shutdown()
        except Exception: pass
        try: _server.server_close()
        except Exception: pass
        log_info("服务已停止 | Server stopped")
        _server = None

if __name__ == "__main__":
    # 命令行直接运行: 前台绑定 0.0.0.0 供局域网访问, 阻塞等待
    srv = start_server(host="0.0.0.0", daemon=False)
    print(f"✅ 已启动: 浏览器打开 http://127.0.0.1:{PORT}/  (局域网白名单模式, 仅放行 {sorted(ALLOWED_IPS)})")
    try:
        while srv._serving_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()