"""PixivFavSearch - 本地书签搜索工具
启动后浏览器打开 http://127.0.0.1:8897/
输入标题关键词 -> 列出匹配作品(标题/作者/链接/缩略图)
缩略图按需下载并缓存到 data/thumbs/
"""
VERSION = "1.2.0"
import time as _time_mod
_START_TS = _time_mod.time()  # 启动时间戳(健康检查 uptime 用)
UPDATE_CHECK_URL = "https://api.github.com/repos/Hzm66647/PixivFavSearch/releases/latest"
UPDATE_DOWNLOAD_URL = "https://github.com/Hzm66647/PixivFavSearch/releases/latest/download/PixivFavSearch.exe"

# --- 更新检查 ---
def check_update():
    """检查是否有新版本"""
    try:
        req = urllib.request.Request(
            UPDATE_CHECK_URL,
            headers={"User-Agent": "PixivFavSearch/" + VERSION}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        latest_ver = (data.get("tag_name") or "").lstrip("v")
        download_url = data.get("browser_download_url") or UPDATE_DOWNLOAD_URL
        changelog = data.get("body") or "无更新说明"
        published = data.get("published_at") or ""
        
        # 比较版本
        def ver_tuple(v):
            try: return tuple(int(x) for x in v.split("."))
            except: return (0,)
        
        has_update = ver_tuple(latest_ver) > ver_tuple(VERSION)
        
        return {
            "ok": True,
            "hasUpdate": has_update,
            "currentVer": VERSION,
            "latestVer": latest_ver,
            "downloadUrl": download_url,
            "changelog": changelog[:500],
            "publishedAt": published,
            "checkTime": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def download_update(download_url):
    """下载更新到临时目录"""
    try:
        temp_dir = os.path.join(os.environ.get("TEMP", ""), "PixivFavSearch_Update")
        os.makedirs(temp_dir, exist_ok=True)
        download_path = os.path.join(temp_dir, "PixivFavSearch_new.exe")
        
        # 下载文件
        req = urllib.request.Request(download_url, headers={"User-Agent": "PixivFavSearch"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(download_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        
        return {"ok": True, "path": download_path}
    except Exception as e:
        return {"ok": False, "error": str(e)}

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
CONFIG_FILE = os.path.join(APP_DATA, "config.json")
os.makedirs(THUMB, exist_ok=True)


# ---------------------------------------------------------------------- 
# 自动备份: 数据文件变化时留快照(保留最近 N 份), 防导入失败/误删砸库
# ----------------------------------------------------------------------
BACKUP_DIR = os.path.join(APP_DATA, "backup")
BACKUP_KEEP = 5          # 每个文件保留份数
BACKUP_MIN_INTERVAL = 300  # 同一文件两次备份最小间隔(秒), 防频繁导入刷爆
_backup_last = {}

def backup_data_file(path, label=""):
    """path 变化时复制一份到 backup/ 目录(带时间戳), 超额删旧。"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 10:
            return False
        now = time.time()
        last = _backup_last.get(path, 0)
        if now - last < BACKUP_MIN_INTERVAL:
            return False
        os.makedirs(BACKUP_DIR, exist_ok=True)
        base = os.path.basename(path)
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"{base}.{ts}{label}")
        import shutil
        shutil.copy2(path, dst)
        _backup_last[path] = now
        # 清理超额旧备份(按修改时间排序删最旧)
        prefix = base + "."
        olds = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.startswith(prefix)],
            key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)))
        while len(olds) > BACKUP_KEEP:
            try:
                os.remove(os.path.join(BACKUP_DIR, olds.pop(0)))
            except OSError:
                break
        return True
    except Exception:
        return False


# 草稿设置
_draft_file = os.path.join(APP_DATA, "draft.json")
def _get_draft_settings():
    """获取草稿设置"""
    if os.path.exists(_draft_file):
        try:
            with open(_draft_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}
def _save_draft_settings(data):
    """保存草稿设置"""
    try:
        os.makedirs(APP_DATA, exist_ok=True)
        with open(_draft_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"草稿保存失败: {e}")
def _clear_draft_settings():
    """清除草稿设置"""
    try:
        if os.path.exists(_draft_file):
            os.remove(_draft_file)
    except:
        pass

# --- 配置持久化(config.json) ---
def load_config():
    """加载配置文件,不存在则返回默认值"""
    if os.path.exists(CONFIG_FILE):
        try:
            return json.load(open(CONFIG_FILE, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"proxy": "http://127.0.0.1:10808"}

def save_config(config):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def get_proxy():
    """从 config.json 读取代理地址, 默认 http://127.0.0.1:10808"""
    return load_config().get("proxy", "http://127.0.0.1:10808")
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
    # Pixiv 官方 R18 判断: xRestrict(0=安全,1=R18,2=R18G) + sl(敏感度 0-6)
    is_r18_xrestrict = it.get("xRestrict", 0) > 0
    is_r18_sl = it.get("sl", 0) >= 6
    r18_tags = {"r-18", "r-18g", "r18", "r18g"}
    tags = [t.strip().lower() if isinstance(t, str) else str(t).strip().lower() for t in it.get("tags") or []]
    is_r18_tag = any(t in r18_tags for t in tags)
    o["isR18"] = is_r18_xrestrict or is_r18_sl or is_r18_tag
    # isMasked: 作品被隐藏/删除
    img_url = it.get("url", "")
    is_masked_url = "limit_" in img_url or "common/images/" in img_url or not img_url
    o["isMasked"] = it.get("isMasked", False) or is_masked_url
    # 作品链接
    o["origUrl"] = img_url  # 原图/大图 URL(查看器用); isMasked 判断已在上面用过 img_url
    o["url"] = f"https://www.pixiv.net/artworks/{o['id']}"
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

BOOKMARKS, BOOKMARKS_LOAD_TIME = _load_pixiv_data()
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
            # 备份旧数据(在覆盖内存前留快照, 防新数据有问题时能回滚)
            backup_data_file(DATA, ".pre-reload")
            _build_pixiv_index(data)
            BOOKMARKS = data
            BOOKMARKS_LOAD_TIME = mtime
            print(f"pixiv 数据热更新: {len(BOOKMARKS)} 幅书签")
            log_info(f"收藏数据热更新 {len(BOOKMARKS)} 条 | Bookmark data hot-reloaded: {len(BOOKMARKS)} items")
        except Exception as e:
            print("pixiv 热更新失败:", repr(e))
            log_error(f"收藏数据热更新失败: {repr(e)} | Bookmark hot-reload failed: {repr(e)}")

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
            msg = "导入失败。Edge 浏览器正在运行导致无法读取 cookie，请先关闭 Edge 浏览器，然后再点导入"
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
THUMB_SEM = threading.Semaphore(8)

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

# ----------------------------------------------------------------------
# 缩略图失败缓存: 下载失败的作品(如 limit_ 被限制图)记录下来, 24h 内不再重试
# 防止每次刷新都发几百个注定 403 的请求
# ----------------------------------------------------------------------
_THUMB_FAIL_FILE = os.path.join(APP_DATA, "thumb_failed.json")
_thumb_fail = {}          # pid -> 失败时间戳
_thumb_fail_loaded = False
_THUMB_FAIL_TTL = 86400   # 24h 后允许重试(作品可能解除限制)

def _load_thumb_fail():
    global _thumb_fail, _thumb_fail_loaded
    if _thumb_fail_loaded:
        return
    _thumb_fail_loaded = True
    try:
        if os.path.exists(_THUMB_FAIL_FILE):
            raw = json.load(open(_THUMB_FAIL_FILE, encoding="utf-8"))
            now = time.time()
            # 过期清理
            _thumb_fail = {k: v for k, v in raw.items() if now - v < _THUMB_FAIL_TTL}
    except Exception:
        _thumb_fail = {}   # 文件损坏(并发写坏) → 丢弃重建

_THUMB_FAIL_SAVE = threading.Lock()

def _mark_thumb_fail(pid):
    # 并发安全: 预载多线程同时标记失败, 不加锁会写坏 JSON
    with _THUMB_FAIL_SAVE:
        _load_thumb_fail()
        _thumb_fail[str(pid)] = time.time()
        try:
            tmp = _THUMB_FAIL_FILE + ".tmp"
            json.dump(_thumb_fail, open(tmp, "w", encoding="utf-8"))
            os.replace(tmp, _THUMB_FAIL_FILE)
        except Exception:
            pass

def _make_placeholder_thumb(pid, title=""):
    """为永久拿不到图的作品(limit_/已删除)生成本地 SVG 占位图。
    带"已失效"标识和作品ID, 比纯色块友好; 生成一次永久复用。"""
    pid = str(pid)
    local = os.path.join(THUMB, pid + ".svg")
    if os.path.exists(local):
        return local
    try:
        t = (title or "")[:18].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600">'
               '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
               '<stop offset="0" stop-color="#2a2440"/><stop offset="1" stop-color="#171226"/>'
               '</linearGradient></defs>'
               '<rect width="600" height="600" fill="url(#g)"/>'
               '<circle cx="300" cy="262" r="74" fill="none" stroke="#5c5478" stroke-width="10"/>'
               '<line x1="248" y1="314" x2="352" y2="210" stroke="#5c5478" stroke-width="10" stroke-linecap="round"/>'
               '<text x="300" y="392" text-anchor="middle" fill="#8a80a8" font-size="30" font-family="sans-serif">作品已失效</text>'
               '<text x="300" y="436" text-anchor="middle" fill="#5c5478" font-size="22" font-family="sans-serif">ID ' + pid + '</text>'
               '<text x="300" y="480" text-anchor="middle" fill="#453d60" font-size="18" font-family="sans-serif">' + t + '</text>'
               '</svg>')
        with open(local, "w", encoding="utf-8") as f:
            f.write(svg)
        return local
    except Exception:
        return None

def _is_thumb_failed(pid):
    _load_thumb_fail()
    ts = _thumb_fail.get(str(pid))
    return ts is not None and (time.time() - ts) < _THUMB_FAIL_TTL

# ----------------------------------------------------------------------
# 缩略图全量预载: 后台线程从最新到最旧批量下载, 断点续传, 进度可查
# ----------------------------------------------------------------------
_PREFETCH = {
    "running": False, "stop": False,
    "total": 0, "done": 0, "ok": 0, "fail": 0, "skip": 0,
    "cur": "", "t_start": 0.0, "finished_at": 0.0, "last_error": "",
}
_PREFETCH_LOCK = threading.Lock()

def start_thumb_prefetch():
    """启动全量预载(已在跑则返回 False)。按 BOOKMARKS 顺序 = 收藏时间倒序(最新→最旧)。"""
    with _PREFETCH_LOCK:
        if _PREFETCH["running"]:
            return False
        _PREFETCH.update({"running": True, "stop": False, "done": 0, "ok": 0,
                          "fail": 0, "skip": 0, "cur": "", "t_start": time.time(),
                          "last_error": ""})
        # 手动启动预载时清空失败缓存: 给瞬时失败的图重试机会
        # (limit_ 图走占位图逻辑不受影响)
        global _thumb_fail
        _thumb_fail = {}
        try:
            if os.path.exists(_THUMB_FAIL_FILE):
                os.remove(_THUMB_FAIL_FILE)
        except Exception:
            pass
        # 待下载数量(排除已缓存; limit_ 图会生成占位图也算待处理)
        _PREFETCH["total"] = sum(
            1 for it in BOOKMARKS
            if not _thumb_cached(str(it.get("id", "")))
            and ("i.pximg.net" in (it.get("url") or "") or "s.pximg.net" in (it.get("url") or "")))
    threading.Thread(target=_prefetch_worker, daemon=True).start()
    return True

def _thumb_cached(pid):
    # .jpg = 真图; .svg = 占位图(也算已处理, 不再重试)
    for ext in (".jpg", ".svg"):
        local = os.path.join(THUMB, pid + ext)
        try:
            if os.path.exists(local) and os.path.getsize(local) > 100:
                return True
        except Exception:
            pass
    return False

def _prefetch_one(it):
    """处理单个作品的缩略图(预载并发单元)。"""
    pid = str(it.get("id", ""))
    url = it.get("url") or ""
    if not pid:
        return
    if _thumb_cached(pid):
        return
    # limit_ 图: 秒生成占位图(不发网络请求)
    if "s.pximg.net" in url or "limit_" in url:
        _make_placeholder_thumb(pid, it.get("title", ""))
        with _PREFETCH_LOCK:
            _PREFETCH["ok"] += 1
            _PREFETCH["done"] += 1
        return
    if "i.pximg.net" not in url:
        with _PREFETCH_LOCK:
            _PREFETCH["skip"] += 1
            _PREFETCH["done"] += 1
        return
    _PREFETCH["cur"] = pid
    try:
        local = thumb_for(it, "zh")
        if local and os.path.getsize(local) > 100:
            with _PREFETCH_LOCK:
                _PREFETCH["ok"] += 1
        else:
            with _PREFETCH_LOCK:
                _PREFETCH["fail"] += 1
    except Exception as e:
        with _PREFETCH_LOCK:
            _PREFETCH["fail"] += 1
            _PREFETCH["last_error"] = repr(e)[:80]
    with _PREFETCH_LOCK:
        _PREFETCH["done"] += 1
    time.sleep(0.04)  # 温和限速(并发下每线程间隔)

def _prefetch_worker():
    """预载线程: 3 并发分片下载(最新→最旧), 比串行快 ~3 倍。"""
    try:
        items = [it for it in list(BOOKMARKS)  # BOOKMARKS 顺序 = 收藏时间倒序
                 if not _thumb_cached(str(it.get("id", "")))]
        # 分 3 片并发(每片内部保序)
        def _slice_run(sl):
            for it in sl:
                if _PREFETCH["stop"]:
                    return
                _prefetch_one(it)
        import queue as _q
        shards = [items[i::6] for i in range(6)]
        threads = [threading.Thread(target=_slice_run, args=(s,), daemon=True) for s in shards]
        for t in threads: t.start()
        for t in threads: t.join()
        # 兼容: 下方原循环改为只处理已缓存跳过统计(不再重复下载)
        for it in list(BOOKMARKS):
            if _PREFETCH["stop"]:
                break
            pid = str(it.get("id", ""))
            if _thumb_cached(pid):
                _PREFETCH["skip"] += 1
                _PREFETCH["done"] += 1
        return
        # (原串行逻辑保留在下方, 不可达, 仅作历史参考)
        for it in list(BOOKMARKS):  # BOOKMARKS 顺序 = 收藏时间倒序
            if _PREFETCH["stop"]:
                break
            pid = str(it.get("id", ""))
            url = it.get("url") or ""
            if not pid:
                _PREFETCH["skip"] += 1
                _PREFETCH["done"] += 1
                continue
            if _thumb_cached(pid):
                _PREFETCH["skip"] += 1
                _PREFETCH["done"] += 1
                continue
            # limit_ 图: 秒生成占位图(不发网络请求)
            if "s.pximg.net" in url or "limit_" in url:
                _make_placeholder_thumb(pid, it.get("title", ""))
                _PREFETCH["ok"] += 1
                _PREFETCH["done"] += 1
                continue
            if "i.pximg.net" not in url:
                _PREFETCH["skip"] += 1
                _PREFETCH["done"] += 1
                continue
            _PREFETCH["cur"] = pid
            try:
                local = thumb_for(it, "zh")
                if local and os.path.getsize(local) > 500:
                    _PREFETCH["ok"] += 1
                else:
                    _PREFETCH["fail"] += 1
            except Exception as e:
                _PREFETCH["fail"] += 1
                _PREFETCH["last_error"] = repr(e)[:80]
            _PREFETCH["done"] += 1
            time.sleep(0.04)  # 温和限速(并发下每线程间隔), 不抢正常请求的带宽
    finally:
        _PREFETCH["running"] = False
        _PREFETCH["finished_at"] = time.time()
        log_info(f"缩略图预载完成: 成功{_PREFETCH['ok']} 失败{_PREFETCH['fail']} 跳过{_PREFETCH['skip']} | "
                 f"Thumb prefetch done: ok={_PREFETCH['ok']} fail={_PREFETCH['fail']} skip={_PREFETCH['skip']}")

def stop_thumb_prefetch():
    _PREFETCH["stop"] = True
    return True

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
    # 失败缓存: 近期下载失败的作品不再重试,
    # 防止每次刷新都发几百个注定 403 的请求占满下载信号量
    if _is_thumb_failed(pid):
        # 永久失败 → 占位图(带"已失效"标识, 不是纯色块)
        return _make_placeholder_thumb(pid, item.get("title", ""))
    url = item.get("url", "")
    # limit_ 图 = pixiv 已删除/私密化, API 也拿不到 → 直接占位图, 不浪费请求
    if "s.pximg.net" in url or "limit_" in url:
        return _make_placeholder_thumb(pid, item.get("title", ""))
    if not url or "i.pximg.net" not in url:
        # url 缺失或不是图片 URL, 尝试从 pixiv API 获取
        url = _fetch_thumb_url_from_api(pid)
        if not url:
            return None
    # 提升缩略图分辨率 (250x250 → 480x480)
    # 预载优先 250 原图(0.26s/张, 比 600x600 快 2.7 倍, 缩略图场景够用);
    # 查看器大图走前端 origUrl 1200 替换, 不依赖这里。
    # (600x600 保留在回退链: 250 失败时尝试)
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
            try:
                with opener.open(req, timeout=12) as r, open(local, "wb") as f:
                    data = r.read(5 * 1024 * 1024 + 1)
                    if len(data) > 5 * 1024 * 1024:
                        return None
                    f.write(data)
            except urllib.error.HTTPError:
                # 600x600 失败(如老图无此尺寸) → 回退原始 250x250 URL 再试一次
                orig_url = (item.get("url", "") or "").replace("custom-thumb", "custom-thumb")
                if orig_url and orig_url != url:
                    req2 = urllib.request.Request(orig_url, headers={
                        "Referer": "https://www.pixiv.net/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                    })
                    with opener.open(req2, timeout=12) as r, open(local, "wb") as f:
                        data = r.read(5 * 1024 * 1024 + 1)
                        if len(data) > 5 * 1024 * 1024:
                            return None
                        f.write(data)
            return local if os.path.getsize(local) > 500 else None
        except Exception as e:
            _mark_thumb_fail(pid)   # 记入失败缓存, 24h 内不再重试(期间用占位图)
            if not hasattr(thumb_for, '_err_logged'):
                thumb_for._err_logged = set()
            err_key = type(e).__name__
            if err_key not in thumb_for._err_logged:
                thumb_for._err_logged.add(err_key)
                _log(f"缩略图下载失败: {e} | Thumb download failed: {e}")
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
        # 优先使用高清图 (regular > small > thumb)
        urls = body.get("urls", {})
        url = (urls.get("regular") or 
               urls.get("small") or 
               urls.get("thumb") or 
               urls.get("mini") or "")
        # 提升缩略图分辨率
        url = url.replace("250x250_80_a2", "480x480_80_a2")
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
        """API 限速(按路径类型分桶): /api/ 60次/5s; /thumb/ 300次/5s; ?key= 30次/5s。
        分桶原因: 一页渲染 200 张缩略图会把共享桶填满, 翻页的 /api/search
        被 429 吞掉 → 页码在累积但内容不更新 → "点几下没反应然后飞页"。
        (ip, kind) 各自独立计数, 互不挤占。"""
        ip = self.client_address[0]
        now = time.time()
        if self.path.startswith("/api/"):
            kind, cap = "api", 60
        elif self.path.startswith("/thumb/"):
            kind, cap = "thumb", 300   # 一页200张+翻页余量, 全缓存时毫秒级返回
        elif self.path.startswith("/") and "key=" in self.path:
            kind, cap = "key", 30   # key 校验端点: 防暴力枚举
        else:
            return True
        key = (ip, kind)
        with _RATE_LOCK:
            t = [x for x in _RATE.get(key, []) if now - x < 5.0]
            if len(t) >= cap:
                _RATE[key] = t
                return False
            t.append(now)
            _RATE[key] = t
            # 防条目无限增长: 超过 600 个桶时清理过期条目
            if len(_RATE) > 600:
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
            # 统计面板专用筛选参数(精确匹配, 不走模糊搜索):
            #   author=作者名 / year=年份 / tag2=标签(与 tag 等价但不受 latin-1 转码影响)
            f_author = urllib.parse.parse_qs(u.query).get("author", [""])[0].strip()
            f_year = urllib.parse.parse_qs(u.query).get("year", [""])[0].strip()
            f_tag2 = urllib.parse.parse_qs(u.query).get("tag2", [""])[0].strip()
            if f_tag2:
                tagf = f_tag2.lower()
            # 确保中文标签正确解码
            try:
                tagf = tagf.encode('latin-1').decode('utf-8') if tagf else ""
            except:
                pass
            # ---- 高级搜索语法解析: 空格=AND, | =OR, -词=排除, 支持括号 ----
            # 例: "和服 浴衣 -R18" / "(和服|浴衣) 蓝色" / "-触手"
            def _parse_bool_query(query):
                """返回 (must_terms, or_groups, not_terms)
                must_terms: 必须全部命中的词(AND)
                or_groups: 每组是 OR 列表, 组内任一命中即可(组间 AND)
                not_terms: 任一命中即排除(NOT)"""
                must, ors, nots = [], [], []
                # 按括号分组提取: (a|b) 作为一个 or_group
                import re as _re2
                parens = _re2.findall(r'\(([^()]+)\)', query)
                rest = _re2.sub(r'\([^()]+\)', ' ', query)
                for p in parens:
                    grp = [w for w in _re2.split(r'[|,，/]', p) if w.strip()]
                    grp = [w.strip() for w in grp if w.strip()]
                    if grp:
                        ors.append(grp)
                for tok in rest.split():
                    if tok.startswith('-') and len(tok) > 1:
                        nots.append(tok[1:].lower())
                    elif '|' in tok or '，' in tok:
                        grp = [w.strip() for w in _re2.split(r'[|,，]', tok) if w.strip()]
                        if len(grp) > 1:
                            ors.append(grp)
                        elif grp:
                            must.append(grp[0].lower())
                    else:
                        must.append(tok.lower())
                return must, ors, nots
            adv_must, adv_ors, adv_nots = _parse_bool_query(q)
            has_adv_syntax = bool(adv_ors or adv_nots) or (len(adv_must) > 1 and ' ' in q)
            q_lower = q.lower()
            # 搜索词脱敏: 只记长度不记内容(防隐私泄露到日志)
            log_debug(f"搜索: 关键词长度={len(q)}, 标签={tagf or '-'}, 收藏标签={colt or '-'} | Search: q_len={len(q)}, tag={tagf or '-'}, coltag={colt or '-'}")
            reload_pixiv_if_changed()  # pixiv 数据热重载(增量更新后免重启)
            q_rom = romanize(q).lower()
            q_norm = _norm_cjk(q).lower()
            q_py = _pinyin(q).lower()
            aliases = [a for k, v in NH_ALIAS.items() if k in q for a in v]
            words = [w for w in q.split() if w]
            # 高级语法: 评分/高亮阶段用净化词(去掉 -/|/() 等语法符号), 布尔粗筛已在上面完成
            if has_adv_syntax:
                import re as _re3
                if adv_must:
                    # 有 AND 词: 用 must 词评分(OR 组已在布尔层放行)
                    clean_q = ' '.join(adv_must)
                    q = clean_q
                    q_lower = q.lower()
                    words = [w for w in q.split() if w]
                elif adv_ors:
                    # 纯 OR 查询: 用第一组的第一个词评分(保证 _match_score 能命中),
                    # 其余 OR 组的命中由布尔层保证 —— 评分只影响排序不影响筛选
                    q = adv_ors[0][0]
                    q_lower = q.lower()
                    words = [q]
                else:
                    # 纯排除词(如 "-触手"): 浏览模式, 布尔粗筛已过滤
                    q_lower = ""
                    words = []
            seg_words = _seg_query(q_lower)
            homophones = _get_homophones(q_lower)
            # 选中的收藏标签允许的作品id集
            coltag_ids = COLTAG_MAP.get(colt) if colt else None
            # 空关键词:进入浏览模式(仅按标签过滤,输词才做匹配)。仅当有力选标签或确实无词全览时
            scored = []
            merged = []
            for it in BOOKMARKS:
                # 限定收藏标签(coltag):作品必须属于该收藏标签
                if coltag_ids is not None and str(it.get("id")) not in coltag_ids:
                    continue
                # 统计面板专用精确筛选: 作者/年份(不走模糊评分, 直接匹配)
                if f_author and (it.get("userName") or "") != f_author:
                    continue
                if f_year and not ((it.get("createDate") or "").startswith(f_year)):
                    continue
                # 限定作品标签过滤:作品的所有标签中要有一个等于 tagf
                tagset = { (t.get("tag") if isinstance(t, dict) else str(t)).lower() for t in (it.get("tags") or []) }
                tagset -= {""}
                if tagf and tagf not in tagset:
                    continue
                # ---- 高级语法布尔过滤(在评分前粗筛) ----
                if has_adv_syntax:
                    hay = it.get("_search", "")
                    # NOT: 任一排除词命中 → 跳过
                    if any(n in hay for n in adv_nots):
                        continue
                    # AND: 必须词全部命中(原文或罗马音/拼音域)
                    hay_rom = it.get("_search_rom", "")
                    hay_py = it.get("_search_py", "")
                    def _hit(term, h, hr, hp):
                        return term in h or term in hr or term in hp
                    if adv_must and not all(_hit(m, hay, hay_rom, hay_py) for m in adv_must):
                        continue
                    # OR 组: 每组内任一命中
                    if adv_ors and not all(any(_hit(o, hay, hay_rom, hay_py) for o in grp) for grp in adv_ors):
                        continue
                if not words:
                    # 空搜索: 不排序, 保持收藏原始顺序(不进入 scored)
                    merged.append(_pub(it, []))
                    continue
                res = _match_score(it, q_lower, q_norm, q_rom, q_py, words, aliases, None, seg_words, homophones)
                if res:
                    score, hitsrc, hl = res
                    scored.append((score, hitsrc, it, hl))
                elif has_adv_syntax:
                    # 高级语法: 布尔层已判定命中(如 OR 组里非首词命中的作品),
                    # 评分函数对不上不代表不匹配 —— 保留, 给低分
                    scored.append((1, "bool-pass", it, []))
            # 按相关度排序(同分保持收藏顺序稳定)
            scored.sort(key=lambda x: (-x[0], x[2].get("id", "")))
            merged += [_pub(it, hl) for _, _, it, hl in scored]
            # 过滤失效作品（始终过滤）
            merged = [m for m in merged if not m.get("isMasked")]
            # 安全模式过滤 R-18（在分页前）
            safe_param = urllib.parse.parse_qs(u.query).get("safe", ["0"])[0]
            safe_mode = safe_param in ("1", "true", "on")
            if safe_mode:
                merged = [m for m in merged if not m.get("isR18")]
            log_debug(f"安全模式: {safe_mode}, 过滤后: {len(merged)}")
            # ---- 排序选项: new(默认=最新收藏,按bookmarkId收藏时间) / old / relevance(搜索相关度,手动选) / author / random ----
            # 注意: createDate 是作品发布日期, 不是收藏时间; bookmarkId 才随收藏单调递增
            sort_param = urllib.parse.parse_qs(u.query).get("sort", ["new"])[0].strip()
            if sort_param == "new":
                merged.sort(key=lambda m: int(m.get("bookmarkId") or 0), reverse=True)
            elif sort_param == "old":
                merged.sort(key=lambda m: int(m.get("bookmarkId") or 0))
            elif sort_param == "author":
                merged.sort(key=lambda m: ((m.get("userName") or "").lower(), m.get("id", "")))
            elif sort_param == "random":
                import random as _rnd
                _rnd.shuffle(merged)
            # relevance / 默认: 保持上面的相关度序
            # 分页支持
            offset = int(urllib.parse.parse_qs(u.query).get("offset", [0])[0])
            limit = int(urllib.parse.parse_qs(u.query).get("limit", [200])[0])
            total = len(merged)
            items = merged[offset:offset+limit]
            self.send_json(200, {"total": total, "items": items, "offset": offset, "limit": limit})
        elif u.path == "/api/stats":
            """收藏统计: 作者排行/标签排行/年度趋势/R18比例, 供统计面板"""
            reload_pixiv_if_changed()
            from collections import Counter
            author_cnt = Counter()
            tag_cnt = Counter()
            year_cnt = Counter()
            n_total = len(BOOKMARKS)
            n_r18 = 0
            n_masked = 0
            for it in BOOKMARKS:
                un = it.get("userName") or ""
                if un and un != "-----":
                    author_cnt[un] += 1
                for t in (it.get("tags") or []):
                    tg = t.get("tag") if isinstance(t, dict) else str(t)
                    if tg:
                        tag_cnt[tg] += 1
                cd = it.get("createDate") or ""
                if cd[:4].isdigit() and cd[:4] not in ("1970",):
                    year_cnt[cd[:4]] += 1
                xr = it.get("xRestrict")
                if xr in (1, 2) or (it.get("sl") or 0) >= 6:
                    n_r18 += 1
                if it.get("isMasked"):
                    n_masked += 1
            self.send_json(200, {
                "total": n_total,
                "r18": n_r18,
                "masked": n_masked,
                "safe": max(0, n_total - n_r18 - n_masked),
                "top_authors": [{"name": k, "count": v} for k, v in author_cnt.most_common(20)],
                "top_tags": [{"tag": k, "count": v} for k, v in tag_cnt.most_common(50)],
                "by_year": [{"year": y, "count": c} for y, c in sorted(year_cnt.items())],
            })
        elif u.path == "/api/health":
            """健康检查: 数据/缓存/磁盘/端口状态, 供诊断用(只读)"""
            def _dir_ok(d):
                try:
                    os.makedirs(d, exist_ok=True)
                    t = os.path.join(d, ".healthcheck")
                    open(t, "w").write("ok")
                    os.remove(t)
                    return True
                except Exception:
                    return False
            try:
                import shutil as _sh
                _du = _sh.disk_usage(APP_DATA)
                disk_free_gb = round(_du.free / (1024**3), 2)
            except Exception:
                disk_free_gb = -1
            n_bookmarks = len(BOOKMARKS)
            n_coltags = sum(len(v) for v in COLTAG_MAP.values())
            n_thumbs = len(os.listdir(THUMB)) if os.path.isdir(THUMB) else 0
            thumb_size_mb = -1
            try:
                thumb_size_mb = round(sum(
                    os.path.getsize(os.path.join(THUMB, f))
                    for f in os.listdir(THUMB) if os.path.isfile(os.path.join(THUMB, f))
                ) / (1024**2), 1)
            except Exception:
                pass
            n_backups = len(os.listdir(BACKUP_DIR)) if os.path.isdir(BACKUP_DIR) else 0
            uptime_s = round(_time_mod.time() - _START_TS, 0)
            self.send_json(200, {
                "ok": True,
                "version": VERSION,
                "uptime_s": uptime_s,
                "data": {
                    "bookmarks": n_bookmarks,
                    "coltag_items": n_coltags,
                    "coltag_groups": len(COLTAG_MAP),
                    "data_writable": _dir_ok(OUT),
                    "thumb_writable": _dir_ok(THUMB),
                },
                "cache": {"thumbs": n_thumbs, "thumbs_mb": thumb_size_mb},
                "disk": {"free_gb": disk_free_gb},
                "backup": {"files": n_backups},
                "import": dict(_import_state),
            })
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
        elif _re.match(r"^/api/coltags/([^/]+)/works$", u.path):
            # GET /api/coltags/{name}/works — 获取标签下的作品
            # (此路由曾在 _handle_post 里但条件是 GET, 永远匹配不到 → 收藏夹点不进去)
            name = urllib.parse.unquote(_re.match(r"^/api/coltags/([^/]+)/works$", u.path).group(1))
            if name not in COLTAG_MAP:
                return self.send_json(404, {"error": "标签不存在"})
            ids = COLTAG_MAP[name]
            items = [_pub(it, []) for it in BOOKMARKS if str(it.get("id")) in ids]
            # limit 参数(收藏夹封面只需要最新几张, 不用全量拉)
            try:
                lim = int(urllib.parse.parse_qs(u.query).get("limit", [0])[0])
            except Exception:
                lim = 0
            if lim > 0:
                items = items[:lim]
            self.send_json(200, {"total": len(COLTAG_MAP[name]), "tag": name, "items": items})
        elif u.path == "/api/thumb-prefetch/status":
            """预载进度查询"""
            p = dict(_PREFETCH)
            p["pending"] = max(0, p["total"] - p["done"])
            if p["running"] and p["done"] > 0 and p["t_start"]:
                rate = p["done"] / max(0.1, time.time() - p["t_start"])
                p["eta_s"] = int(p["pending"] / max(0.01, rate)) if rate > 0 else -1
            else:
                p["eta_s"] = -1
            # 本地缓存总量
            try:
                p["cached"] = sum(1 for f in os.listdir(THUMB) if f.endswith(".jpg"))
            except Exception:
                p["cached"] = -1
            return self.send_json(200, p)

        elif u.path == "/api/settings":
            # 返回当前配置(proxy 等)
            cfg = load_config()
            self.send_json(200, {"proxy": cfg.get("proxy", "http://127.0.0.1:10808")})
        elif u.path == "/api/settings/draft":
            # 返回草稿设置
            draft = _get_draft_settings()
            self.send_json(200, draft)
        elif u.path == "/api/about":
            # 返回版本信息
            v = LATEST_VER
            self.send_json(200, {
                "version": VERSION,
                "github": "https://github.com/Hzm66647/PixivFavSearch",
                "checking": v.get("checking", False),
                "ok": v.get("ok", False),
                "latest": v.get("version"),
                "url": v.get("url"),
                "update": bool(v.get("ok") and v.get("version") and _ver_gt(v["version"], VERSION)),
            })
        elif u.path == "/api/update/check":
            """检查是否有新版本"""
            result = check_update()
            self.send_json(200, result)
        elif u.path == "/api/update/download":
            """下载更新到临时目录"""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                body = {}
            download_url = body.get("url", UPDATE_DOWNLOAD_URL)
            result = download_update(download_url)
            self.send_json(200, result)
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
            pid = os.path.basename(u.path)
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
            # 304 支持: 浏览器带 If-Modified-Since 时零传输(图片不变)
            try:
                mtime = int(os.path.getmtime(local))
                ims = self.headers.get("If-Modified-Since")
                if ims:
                    import email.utils as _eu
                    try:
                        ims_ts = int(_eu.mktime_tz(_eu.parsedate_tz(ims)))
                        if mtime <= ims_ts:
                            self.send_response(304)
                            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                            self.end_headers()
                            return
                    except Exception:
                        pass
            except Exception:
                pass
            with open(local, "rb") as f:
                body = f.read()
            is_svg = local.endswith(".svg")
            ctype = "image/svg+xml" if is_svg else "image/jpeg"
            if is_svg:
                # 占位图(SVG): 可能被真图替换(重试成功后), 不 immutable,
                # 每次用 ETag 验证, 内容变了浏览器自动拉新
                import hashlib as _hl
                etag = '"' + _hl.md5(body).hexdigest()[:16] + '"'
                inm = self.headers.get("If-None-Match")
                if inm and inm == etag:
                    self.send_response(304)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("ETag", etag)
            else:
                # 真图(jpg): 内容永不变化, immutable 浏览器零请求
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("Last-Modified", time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(os.path.getmtime(local))))
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
            ct = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "image/jpeg")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # --- 首次使用引导 API ---
        elif u.path == "/api/first-run/status":
            """返回首次使用状态"""
            import pixiv_export as _pe
            cookies_exist = os.path.exists(_pe.COOKIE_FILE)
            uid = ""
            count = 0
            if cookies_exist:
                try:
                    _c = json.load(open(_pe.COOKIE_FILE, "r", encoding="utf-8"))
                    count = len(_c)
                    uid = _pe._detect_uid(_c)
                except Exception:
                    pass
            # 检查 Edge CDP 是否可用
            edge_available = False
            try:
                import http.client
                _ec = http.client.HTTPConnection("127.0.0.1", 9222, timeout=2)
                _ec.request("GET", "/json")
                _er = _ec.getresponse()
                _et = json.loads(_er.read())
                _ec.close()
                edge_available = any(t.get("type") == "page" for t in _et)
            except Exception:
                pass
            self.send_json(200, {
                "first_run": not cookies_exist,
                "cookies_exist": cookies_exist,
                "cookie_count": count,
                "uid": uid,
                "edge_available": edge_available,
            })

        elif u.path == "/first-run":
            """首次使用引导页（HTML）"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(FIRST_RUN_HTML.encode("utf-8"))

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
        global BOOKMARKS, BOOKMARKS_LOAD_TIME, COLTAG_MAP
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
        if u.path == "/api/first-run/edge":
            """从 Edge CDP 抓取 Pixiv cookie"""
            import pixiv_export as _pe
            cookies = _pe.grab_cookies_from_edge()
            if not cookies:
                return self.send_json(400, {"ok": False, "error": "无法连接 Edge CDP (9222) 或未登录 Pixiv"})
            ok, uid, count = _pe.save_cookies(cookies)
            if ok:
                log_info(f"首次引导: 从 Edge 抓取 {count} 个 cookie, uid={uid}")
                return self.send_json(200, {"ok": True, "uid": uid, "count": count})
            else:
                return self.send_json(500, {"ok": False, "error": "保存 cookie 失败"})

        if u.path == "/api/first-run/webview":
            """从 WebView2 CDP 抓取 Pixiv cookie"""
            import pixiv_export as _pe
            cookies = _pe.grab_cookies_from_webview()
            if not cookies:
                return self.send_json(400, {"ok": False, "error": "WebView2 未登录 Pixiv 或未启动"})
            ok, uid, count = _pe.save_cookies(cookies)
            if ok:
                log_info(f"首次引导: 从 WebView2 抓取 {count} 个 cookie, uid={uid}")
                return self.send_json(200, {"ok": True, "uid": uid, "count": count})
            else:
                return self.send_json(500, {"ok": False, "error": "保存 cookie 失败"})

        if u.path == "/api/first-run/launch-login":
            """导航 WebView2 到登录页（通过 CDP 9223）"""
            try:
                import http.client
                import websocket
                import random
                
                # 连接 CDP
                conn = http.client.HTTPConnection("127.0.0.1", 9223, timeout=3)
                conn.request("GET", "/json")
                resp = conn.getresponse()
                targets = json.loads(resp.read())
                conn.close()
                
                page = next((t for t in targets if t.get("type") == "page"), None)
                if not page:
                    return self.send_json(500, {"ok": False, "error": "WebView2 未启动"})
                
                ws_url = page.get("webSocketDebuggerUrl")
                if not ws_url:
                    return self.send_json(500, {"ok": False, "error": "无法获取 WebView2 WebSocket URL"})
                
                ws = websocket.create_connection(ws_url, timeout=10,
                    http_proxy_host=None, http_proxy_port=None, http_no_proxy=["*"])
                
                # 导航到登录页
                mid = random.randint(1, 999999)
                ws.send(json.dumps({"id": mid, "method": "Page.navigate", "params": {"url": "https://www.pixiv.net/login.php"}}))
                
                # 等待响应
                while True:
                    r = json.loads(ws.recv())
                    if r.get("id") == mid:
                        break
                
                ws.close()
                log_info("首次引导: 已导航 WebView2 到登录页")
                return self.send_json(200, {"ok": True})
                
            except Exception as e:
                log_error(f"首次引导: 导航 WebView2 失败: {e}")
                return self.send_json(500, {"ok": False, "error": str(e)})

        if u.path == "/api/first-run/check":
            """检查 cookies.json 是否已创建（供前端轮询等待登录完成）"""
            import pixiv_export as _pe
            if os.path.exists(_pe.COOKIE_FILE):
                try:
                    _c = json.load(open(_pe.COOKIE_FILE, "r", encoding="utf-8"))
                    uid = _pe._detect_uid(_c)
                    return self.send_json(200, {"ok": True, "ready": True, "uid": uid, "count": len(_c)})
                except Exception:
                    pass
            return self.send_json(200, {"ok": True, "ready": False})

        if u.path == "/api/open-work":
            """前端跳转 pixiv: 通知 desktop_app 开新 WebView 窗口(关掉即回主应用)。
            纯浏览器模式(8897 直开)没有 desktop_app, 前端会兜底 window.open。"""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"ok": False, "error": "bad json"})
            url = data.get("url", "")
            mode = data.get("mode", "browser")   # browser=系统默认浏览器(默认) / inner=应用内窗口(备选)
            # 只允许 pixiv 域名(防开放跳转)
            if not url.startswith("https://www.pixiv.net/"):
                return self.send_json(400, {"ok": False, "error": "domain"})
            opened = False
            try:
                # 回调模式(exe 里 desktop_app 是 __main__, 不能直接 import):
                # browser → webbrowser.open + 托盘气泡(点图标回主应用)
                # inner   → 应用内 WebView 窗口(关掉即回)
                if mode == "inner":
                    _cb = globals().get("_OPEN_EXTERNAL_WINDOW_CB")
                    if _cb:
                        opened = bool(_cb(url))
                else:
                    _cb = globals().get("_OPEN_BROWSER_CB")
                    if _cb:
                        opened = bool(_cb(url))
            except Exception:
                pass
            return self.send_json(200, {"ok": True, "opened": opened, "mode": mode})

        elif u.path == "/api/thumb-prefetch" and self.command == "POST":
            """启动/停止缩略图全量预载(最新→最旧)"""
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                data = {}
            if data.get("stop"):
                stop_thumb_prefetch()
                return self.send_json(200, {"ok": True, "stopping": True})
            started = start_thumb_prefetch()
            return self.send_json(200, {"ok": True, "started": started,
                                        "running": _PREFETCH["running"]})

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

        # --- 收藏标签管理 API ---
        if u.path == "/api/coltags" and self.command == "POST":
            # 创建新收藏标签
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            name = (data.get("name") or "").strip()
            if not name:
                return self.send_json(400, {"error": "标签名不能为空"})
            if name in COLTAG_MAP:
                return self.send_json(400, {"error": "标签已存在"})
            COLTAG_MAP[name] = set()
            # 持久化
            try:
                raw = {}
                for tag, ids in COLTAG_MAP.items():
                    raw[tag] = list(ids)
                with open(COLTAGS, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            except Exception as e:
                return self.send_json(500, {"error": f"保存失败: {e}"})
            return self.send_json(200, {"ok": True, "tag": name, "count": 0})

        # DELETE /api/coltags/{name} — 删除标签
        m_del = _re.match(r"^/api/coltags/([^/]+)$", u.path)
        if m_del and self.command == "DELETE":
            name = urllib.parse.unquote(m_del.group(1))
            if name not in COLTAG_MAP:
                return self.send_json(404, {"error": "标签不存在"})
            del COLTAG_MAP[name]
            try:
                raw = {}
                for tag, ids in COLTAG_MAP.items():
                    raw[tag] = list(ids)
                with open(COLTAGS, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            except Exception as e:
                return self.send_json(500, {"error": f"保存失败: {e}"})
            return self.send_json(200, {"ok": True})

        # POST /api/coltags/{name}/toggle — 切换作品是否在标签中
        m_tog = _re.match(r"^/api/coltags/([^/]+)/toggle$", u.path)
        if m_tog and self.command == "POST":
            name = urllib.parse.unquote(m_tog.group(1))
            if name not in COLTAG_MAP:
                return self.send_json(404, {"error": "标签不存在"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            work_id = str(data.get("work_id", ""))
            if not work_id:
                return self.send_json(400, {"error": "缺少 work_id"})
            added = False
            if work_id in COLTAG_MAP[name]:
                COLTAG_MAP[name].discard(work_id)
            else:
                COLTAG_MAP[name].add(work_id)
                added = True
            try:
                raw = {}
                for tag, ids in COLTAG_MAP.items():
                    raw[tag] = list(ids)
                with open(COLTAGS, "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
            except Exception as e:
                return self.send_json(500, {"error": f"保存失败: {e}"})
            return self.send_json(200, {"ok": True, "added": added, "count": len(COLTAG_MAP[name])})

        # GET /api/coltags/{name}/works — 获取标签下的作品
        # (已搬到 _handle_get: 此处是 POST handler, GET 请求永远进不来)

        # --- 设置 API ---
        if u.path == "/api/settings" and self.command == "POST":
            # 更新配置
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            cfg = load_config()
            if "proxy" in data:
                cfg["proxy"] = data["proxy"]
            if save_config(cfg):
                return self.send_json(200, {"ok": True})
            return self.send_json(500, {"error": "保存配置失败"})
        if u.path == "/api/settings/draft" and self.command == "GET":
            # 返回草稿设置
            draft = _get_draft_settings()
            return self.send_json(200, draft)
        if u.path == "/api/settings/draft" and self.command == "POST":
            # 保存草稿设置 (不立即应用)
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            _save_draft_settings(data)
            return self.send_json(200, {"ok": True})
        if u.path == "/api/settings/draft/apply" and self.command == "POST":
            # 应用草稿设置
            try:
                n = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except Exception:
                return self.send_json(400, {"error": "JSON 解析失败"})
            cfg = load_config()
            allowed = {"proxy"}
            for k in allowed:
                if k in data:
                    cfg[k] = data[k]
            if save_config(cfg):
                _clear_draft_settings()
                return self.send_json(200, {"ok": True})
            return self.send_json(500, {"error": "应用失败"})
        if u.path == "/api/settings/draft/cancel" and self.command == "POST":
            # 取消草稿 (不保存)
            _clear_draft_settings()
            return self.send_json(200, {"ok": True})

        if u.path == "/api/settings/clear-cookies" and self.command == "POST":
            # 清除 cookie
            import pixiv_export as _pe
            if os.path.exists(_pe.COOKIE_FILE):
                try:
                    os.remove(_pe.COOKIE_FILE)
                    return self.send_json(200, {"ok": True})
                except Exception as e:
                    return self.send_json(500, {"error": str(e)})
            return self.send_json(200, {"ok": True})

        if u.path == "/api/settings/clear-data" and self.command == "POST":
            # 清除所有收藏数据
            try:
                if os.path.exists(DATA):
                    os.remove(DATA)
                if os.path.exists(COLTAGS):
                    os.remove(COLTAGS)
                with PIXIV_LOCK:
                    BOOKMARKS = []
                    BOOKMARKS_LOAD_TIME = 0.0
                    COLTAG_MAP = {}
                return self.send_json(200, {"ok": True})
            except Exception as e:
                return self.send_json(500, {"error": str(e)})

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


FIRST_RUN_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PixivFavSearch — 首次使用设置</title>

<style>
:root{
  --bg:#000;--glass:rgba(255,55,255,.07);--glass-bd:rgba(255,255,255,.12);
  --accent:#c77dff;--accent-g:rgba(199,125,255,.5);
  --txt:#fff;--sub:rgba(255,255,255,.55);--green:#34c759;
  --ease-power:cubic-bezier(.16,1,.3,1);
  --ease-punch:cubic-bezier(.22,1.4,.36,1);
  --ease-snap:cubic-bezier(.34,1.56,.64,1);
}

:root{--bg:#000;--glass:rgba(255,255,255,.07);--glass-bd:rgba(255,255,255,.12);--accent:#c77dff;--accent-g:rgba(199,125,255,.5);--txt:#fff;--sub:rgba(255,255,255,.55);--green:#34c759;--ease-power:cubic-bezier(.16,1,.3,1);--ease-punch:cubic-bezier(.22,1.4,.36,1);--ease-snap:cubic-bezier(.34,1.56,.64,1)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','PingFang SC',sans-serif;background:var(--bg);color:var(--txt);height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased;transition:background .4s}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(80% 60% at 15% 25%,rgba(100,50,200,.3) 0%,transparent 55%),radial-gradient(70% 90% at 85% 75%,rgba(180,80,220,.2) 0%,transparent 50%);pointer-events:none;z-index:0;transition:background .4s}

/* 安全角落提示 */
.safe-dot{position:fixed;bottom:18px;left:50%;transform:translateX(-50%) translateY(8px);background:var(--glass);backdrop-filter:blur(20px);border:1px solid rgba(52,199,89,.3);border-radius:16px;padding:6px 14px;font-size:11px;color:var(--green);display:flex;align-items:center;gap:6px;opacity:0;pointer-events:none;transition:all .4s var(--ease-power);z-index:50}
.safe-dot.on{opacity:1;transform:translateX(-50%) translateY(0)}
.safe-dot .dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green)}

/* 侧边栏 */
.sidebar{position:fixed;left:14px;top:50%;transform:translateY(-50%);width:64px;background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:32px;padding:10px 6px;z-index:100;display:flex;flex-direction:column;gap:6px;box-shadow:0 12px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.15);transition:all .4s var(--ease-power)}
.sidebar:hover{transform:translateY(-50%) scale(1.06);box-shadow:0 20px 60px rgba(0,0,0,.6),0 0 80px color-mix(in srgb,var(--accent) 20%,transparent)}
.sb-item{width:52px;height:52px;border-radius:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:22px;color:var(--sub);position:relative;transition:all .35s var(--ease-snap)}
.sb-item:hover{transform:scale(1.22);color:var(--txt);background:rgba(255,255,255,.08)}
.sb-item:active{transform:scale(.88)}
.sb-item.active{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;box-shadow:0 6px 24px var(--accent-g);animation:sbPop .5s var(--ease-punch)}
@keyframes sbPop{0%{transform:scale(.75)}40%{transform:scale(1.3)}60%{transform:scale(.9)}80%{transform:scale(1.1)}100%{transform:scale(1)}}
.sb-tip{position:absolute;left:62px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--glass-bd);padding:8px 14px;border-radius:14px;font-size:13px;white-space:nowrap;opacity:0;transform:translateX(-10px) scale(.8);pointer-events:none;transition:all .3s var(--ease-snap);box-shadow:0 8px 24px rgba(0,0,0,.5)}
.sb-item:hover .sb-tip{opacity:1;transform:translateX(0) scale(1)}

/* 灵动岛 */
.island{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:10px 22px;display:flex;align-items:center;gap:14px;z-index:200;box-shadow:0 10px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.12);transition:all .5s var(--ease-power)}
.island:hover{padding:10px 28px;box-shadow:0 16px 56px rgba(0,0,0,.6),0 0 80px color-mix(in srgb,var(--accent) 15%,transparent)}
.island-btn{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.06);border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;color:var(--txt);transition:all .3s var(--ease-snap)}
.island-btn:hover{transform:scale(1.25);background:var(--accent);box-shadow:0 6px 20px var(--accent-g)}
.island-btn:active{transform:scale(.85)}
.island-txt{font-size:13px;color:var(--sub)}
.island-txt b{color:var(--txt)}

/* 搜索面板 */
.search-float{position:fixed;top:76px;left:50%;transform:translateX(-50%) scale(.9) translateY(-15px);width:min(500px,88vw);background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:26px;padding:18px 22px;display:flex;align-items:center;gap:14px;z-index:180;opacity:0;pointer-events:none;transition:all .5s var(--ease-punch);box-shadow:0 24px 64px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.12)}
.search-float.open{opacity:1;pointer-events:all;transform:translateX(-50%) scale(1) translateY(0)}
.search-float input{flex:1;background:transparent;border:none;color:var(--txt);font-size:17px;font-weight:500;outline:none}
.search-float input::placeholder{color:var(--sub)}

/* 主内容 */
.main{margin-left:92px;height:100vh;overflow:hidden;padding:24px 32px;position:relative}
.page{position:absolute;top:0;left:0;right:0;bottom:0;padding:24px 32px;overflow-y:auto;opacity:0;transform:translateX(20px);transition:opacity .4s var(--ease-power),transform .4s var(--ease-power);pointer-events:none}
.page.active{opacity:1;transform:translateX(0);pointer-events:auto}
.page.exit{opacity:0;transform:translateX(-20px);pointer-events:none}

/* 进度条 */
.progress{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,var(--accent),#e0aaff);width:0;z-index:9999;transition:width .3s;box-shadow:0 0 20px var(--accent-g)}
.progress.active{width:100%;transition:width 8s ease-out}

/* 卡片 */
.masonry{columns:5;column-gap:16px;padding-top:64px}
@media(max-width:1400px){.masonry{columns:4}}
@media(max-width:1100px){.masonry{columns:3}}
@media(max-width:800px){.masonry{columns:2}}

.card{break-inside:avoid;margin-bottom:16px;border-radius:20px;overflow:hidden;position:relative;cursor:pointer;background:var(--glass);backdrop-filter:blur(16px);border:1px solid var(--glass-bd);animation:cardIn .6s var(--ease-punch) both;transition:all .4s var(--ease-snap)}
@keyframes cardIn{from{opacity:0;transform:translateY(30px) scale(.85)}to{opacity:1;transform:translateY(0) scale(1)}}
.card:nth-child(1){animation-delay:0ms}.card:nth-child(2){animation-delay:40ms}.card:nth-child(3){animation-delay:80ms}.card:nth-child(4){animation-delay:120ms}.card:nth-child(5){animation-delay:160ms}.card:nth-child(6){animation-delay:200ms}.card:nth-child(7){animation-delay:240ms}.card:nth-child(8){animation-delay:280ms}.card:nth-child(9){animation-delay:320ms}.card:nth-child(10){animation-delay:360ms}.card:nth-child(11){animation-delay:400ms}.card:nth-child(12){animation-delay:440ms}

.card:hover{transform:translateY(-8px) scale(1.04);box-shadow:0 20px 48px rgba(0,0,0,.5),0 0 40px color-mix(in srgb,var(--accent) 15%,transparent),inset 0 1px 0 rgba(255,255,255,.2);border-color:rgba(255,255,255,.25)}
.card:active{transform:scale(.95);transition-duration:.15s}
.card-img{width:100%;display:block;transition:transform .45s var(--ease-snap)}
.card:hover .card-img{transform:scale(1.06)}
.card-ov{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.9) 0%,transparent 50%);opacity:0;transition:opacity .3s;display:flex;flex-direction:column;justify-content:flex-end;padding:16px}
.card:hover .card-ov{opacity:1}
.card-tt{font-size:13px;font-weight:600;line-height:1.3;transform:translateY(8px);transition:transform .35s var(--ease-snap)}
.card:hover .card-tt{transform:translateY(0)}
.card-au{font-size:11px;color:var(--sub);margin-top:3px;transform:translateY(8px);transition:transform .35s var(--ease-snap) .04s}
.card:hover .card-au{transform:translateY(0)}
.card-act{display:flex;gap:7px;margin-top:10px}
.card-btn{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.1);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;font-size:14px;color:#fff;opacity:0;transform:translateY(10px);transition:all .3s var(--ease-snap)}
.card:hover .card-btn{opacity:1;transform:translateY(0)}
.card-btn:nth-child(2){transition-delay:.06s}
.card-btn:nth-child(3){transition-delay:.12s}
.card-btn:hover{background:var(--accent);transform:scale(1.3);box-shadow:0 6px 20px var(--accent-g)}
.card-btn:active{transform:scale(.85)}
.card-btn.liked{background:#ff3b30;animation:heartBeat .6s var(--ease-punch)}
@keyframes heartBeat{0%{transform:scale(1)}25%{transform:scale(1.5)}45%{transform:scale(.85)}65%{transform:scale(1.25)}85%{transform:scale(.95)}100%{transform:scale(1)}}

/* 标签弹窗 */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;pointer-events:none;transition:opacity .3s}
.modal-bg.open{opacity:1;pointer-events:all}
.modal-box{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:26px;padding:26px;min-width:320px;transform:scale(.85) translateY(16px);transition:transform .45s var(--ease-punch);box-shadow:0 28px 72px rgba(0,0,0,.6)}
.modal-bg.open .modal-box{transform:scale(1) translateY(0)}
.modal-box h3{font-size:16px;margin-bottom:16px;color:var(--accent)}
.tag-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.tag-chip{padding:7px 14px;border-radius:20px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);font-size:13px;cursor:pointer;transition:all .25s var(--ease-snap)}
.tag-chip:hover{background:color-mix(in srgb,var(--accent) 18%,transparent);transform:scale(1.1)}
.tag-chip.on{background:var(--accent);color:#1a0a2e;font-weight:600}
.tag-input{width:100%;padding:12px 16px;border-radius:14px;background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);color:var(--txt);font-size:14px;outline:none;transition:all .25s}
.tag-input:focus{border-color:var(--accent);background:rgba(255,255,255,.08)}

/* 收藏夹 */
.fav-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-top:64px}
.fav-top h2{font-size:21px;font-weight:600}
.fav-add{padding:10px 20px;border-radius:14px;background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;border:none;font-size:14px;font-weight:600;cursor:pointer;transition:all .3s var(--ease-snap);box-shadow:0 4px 20px var(--accent-g)}
.fav-add:hover{transform:scale(1.1) translateY(-2px);box-shadow:0 8px 28px var(--accent-g)}
.fav-add:active{transform:scale(.92)}
.fav-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:20px}
.fav-card{aspect-ratio:3/2;border-radius:20px;overflow:hidden;position:relative;cursor:pointer;transition:all .45s var(--ease-snap);border:1px solid var(--glass-bd)}
.fav-card:hover{transform:scale(1.1) translateY(-10px);box-shadow:0 28px 72px rgba(0,0,0,.7)}
.fav-card-bg{position:absolute;inset:0;transition:transform .5s var(--ease-snap)}
.fav-card:hover .fav-card-bg{transform:scale(1.15)}
.fav-card-info{position:absolute;bottom:0;left:0;right:0;padding:16px;background:linear-gradient(to top,rgba(0,0,0,.85),transparent)}
.fav-card-name{font-size:14px;font-weight:600}
.fav-card-count{font-size:11px;color:var(--sub);margin-top:3px}
.back-btn{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);color:var(--txt);font-size:14px;cursor:pointer;transition:all .3s var(--ease-snap);margin-bottom:20px}
.back-btn:hover{background:rgba(255,255,255,.1);transform:translateX(-6px)}
.back-btn:active{transform:scale(.95)}

/* 设置 */
.sec{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:22px;margin-bottom:18px;transition:all .35s var(--ease-power);box-shadow:0 8px 32px rgba(0,0,0,.3)}
.sec:hover{transform:translateX(6px)}
.sec h3{font-size:15px;color:var(--accent);margin-bottom:16px;display:flex;align-items:center;gap:8px}
.set-row{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.set-row:last-child{border-bottom:none}
.set-label{font-size:14px;font-weight:500}
.set-desc{font-size:11px;color:var(--sub);margin-top:3px}
.set-input{padding:10px 14px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;width:220px;outline:none;transition:all .25s}
.set-input:focus{border-color:var(--accent);background:rgba(255,255,255,.08)}
.tog{width:52px;height:32px;border-radius:16px;background:rgba(255,255,255,.12);position:relative;cursor:pointer;transition:background .35s var(--ease-power)}
.tog.on{background:var(--green)}
.tog::after{content:'';position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;transition:transform .4s var(--ease-punch);box-shadow:0 2px 8px rgba(0,0,0,.3)}
.tog.on::after{transform:translateX(20px)}
.btn{padding:10px 20px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;cursor:pointer;transition:all .3s var(--ease-snap)}
.btn:hover{background:rgba(255,255,255,.12);transform:translateY(-2px)}
.btn:active{transform:scale(.94)}
.btn-red{border-color:rgba(255,80,80,.3);color:#ff6b6b}
.btn-red:hover{background:rgba(255,80,80,.15)}
.btn-primary{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;border:none;font-weight:600}
.btn-primary:hover{box-shadow:0 8px 24px var(--accent-g)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:22px}
.stat{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:22px;text-align:center;transition:all .4s var(--ease-snap)}
.stat:hover{transform:translateY(-6px) scale(1.04);box-shadow:0 16px 48px rgba(0,0,0,.4)}
.stat-v{font-size:32px;font-weight:700;color:var(--accent)}
.stat-l{font-size:12px;color:var(--sub);margin-top:6px}

/* 主题面板 (大) */
.theme-panel{position:fixed;top:0;right:-480px;width:460px;height:100vh;background:rgba(15,10,25,.96);backdrop-filter:blur(40px);border-left:1px solid var(--glass-bd);z-index:9999;padding:24px 20px;overflow-y:auto;transition:right .5s var(--ease-punch);box-shadow:-16px 0 48px rgba(0,0,0,.5)}
.theme-panel.open{right:0}
.theme-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.theme-hdr h2{font-size:17px}
.theme-close{width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,.08);border:none;color:var(--txt);cursor:pointer;transition:all .25s var(--ease-snap);display:flex;align-items:center;justify-content:center}
.theme-close:hover{background:rgba(255,255,255,.15);transform:scale(1.15)}
.theme-close:active{transform:scale(.9)}
.theme-sec{background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);border-radius:16px;padding:16px;margin-bottom:14px}
.theme-sec h4{font-size:13px;color:var(--accent);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.color-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.color-swatch{aspect-ratio:1;border-radius:12px;cursor:pointer;transition:all .25s var(--ease-snap);border:2px solid transparent;position:relative}
.color-swatch:hover{transform:scale(1.2)}
.color-swatch.on{border-color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.4)}
.color-swatch.on::after{content:'✓';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.5)}
.custom-row{display:flex;gap:10px;align-items:center}
.color-picker{width:40px;height:40px;border-radius:10px;border:2px solid var(--glass-bd);cursor:pointer;overflow:hidden;transition:transform .2s}
.color-picker:hover{transform:scale(1.1)}
.color-picker input{width:150%;height:150%;margin:-25%;border:none;cursor:pointer}
.bg-preview{width:100%;height:70px;border-radius:12px;background:rgba(255,255,255,.04);border:2px dashed var(--glass-bd);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .3s;overflow:hidden;position:relative}
.bg-preview:hover{border-color:var(--accent);background:rgba(255,255,255,.06)}
.bg-preview.has-img{border-style:solid}
.bg-preview img{width:100%;height:100%;object-fit:cover}
.bg-txt{font-size:11px;color:var(--sub);text-align:center}
.bg-rm{position:absolute;top:5px;right:5px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;border:none;cursor:pointer;font-size:10px;opacity:0;transition:opacity .2s}
.bg-preview:hover .bg-rm{opacity:1}

/* 拉条 */
.slider-row{padding:8px 0}
.slider-row .labels{display:flex;justify-content:space-between;font-size:10px;color:var(--sub);margin-bottom:6px}
.slider-row .labels .rec{color:var(--accent);font-weight:600}
.val-tag{display:inline-block;padding:2px 8px;border-radius:8px;background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);font-size:11px;font-weight:600;min-width:32px;text-align:center}
input[type=range]{-webkit-appearance:none;width:100%;height:5px;border-radius:3px;background:rgba(255,255,255,.08);outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4);transition:transform .2s var(--ease-snap)}
input[type=range]::-webkit-slider-thumb:active{transform:scale(1.1)}
.rec-tag{color:var(--accent);font-weight:600;font-size:11px}
.rec-mark{position:absolute;top:20px;width:2px;height:8px;background:var(--accent);transform:translateX(-50%);border-radius:1px;pointer-events:none}

/* 冲突警告 */
.conflict-warn{background:rgba(255,152,0,.12);border:1px solid rgba(255,152,0,.3);border-radius:12px;padding:10px 14px;margin-top:10px;font-size:11px;color:#ff9800;display:none;align-items:center;gap:8px}
.conflict-warn.show{display:flex}
.conflict-warn .warn-ico{font-size:16px}

/* 开关行 */
.fx-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.03)}
.fx-row:last-child{border-bottom:none}
.fx-label{display:flex;align-items:center;gap:8px;font-size:13px}
.fx-label .ico{font-size:16px}
.fx-tog{width:44px;height:26px;border-radius:13px;background:rgba(255,255,255,.1);position:relative;cursor:pointer;transition:background .3s var(--ease-power)}
.fx-tog.on{background:var(--accent)}
.fx-tog::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .35s var(--ease-punch);box-shadow:0 2px 6px rgba(0,0,0,.3)}
.fx-tog.on::after{transform:translateX(18px)}

::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.06);border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.12)}


.draft-tip{position:fixed;top:60px;left:50%;transform:translateX(-50%) translateY(-10px);background:var(--accent);color:#fff;padding:8px 16px;border-radius:12px;font-size:12px;font-weight:600;opacity:0;pointer-events:none;transition:all .3s;z-index:99999}
.draft-tip.show{opacity:1;transform:translateX(-50%) translateY(0)}
.set-actions{display:flex;gap:8px;justify-content:flex-end}
.btn-ghost{padding:8px 16px;border-radius:10px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;font-weight:600;cursor:pointer;transition:all .3s}
.btn-ghost:hover{background:rgba(255,255,255,.1)}
</style>
</head>
<body>
<!-- 灵动岛 -->
<div class="island" id="island">
  <button class="island-btn" onclick="document.getElementById('q').focus()" title="搜索 (/)">🔍</button>
  <span class="island-txt"><b>PixivFavSearch</b> · <span id="island-count">0</span> 幅</span>
  <button class="island-btn" id="refresh-btn" onclick="refreshAll()" title="刷新 (F5)">🔄</button>
  <button class="island-btn" onclick="doImport()" title="导入收藏">📥</button>
  <button class="island-btn" onclick="toggleTheme()" title="主题">🎨</button>
</div>

<!-- 更新提示条 -->
<div class="update-bar" id="update-bar">
 <span class="ub-ico">🎉</span>
 <div class="ub-txt">
  <div class="ub-ver" id="ub-ver">有可用更新</div>
  <div class="ub-cl" id="ub-cl">发现新版本</div>
 </div>
 <button class="ub-btn go" onclick="doUpdate()">更新</button>
 <button class="ub-btn later" onclick="this.parentElement.classList.remove('show')">稍后</button>
</div>

<!-- 主题面板 -->
<div class="theme-panel" id="theme-panel">
  <div class="theme-hdr"><h2>主题 & 动效</h2><button class="theme-close" onclick="toggleTheme()">✕</button></div>
  <div class="theme-sec"><h4>基础</h4><div class="color-grid" id="preset-themes"></div>
   <div style="margin-top:10px"><div class="custom-row"><div class="color-picker"><input type="color" id="pick-accent" value="#c77dff" onchange="applyAccent(this.value)"></div><input class="set-input" id="txt-accent" value="#c77dff" onchange="applyAccent(this.value)" style="flex:1"></div></div>
   <div style="margin-top:8px"><div class="custom-row"><div class="color-picker"><input type="color" id="pick-bg" value="#000" onchange="applyBg(this.value)"></div><input class="set-input" id="txt-bg" value="#000" onchange="applyBg(this.value)" style="flex:1"></div></div>
   <div class="bg-preview" id="bg-preview" onclick="document.getElementById('bg-file').click()"><span class="bg-txt">📷 导入图片</span><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button></div>
   <input type="file" id="bg-file" accept="image/*" style="display:none" onchange="handleBg(this)">
  </div>
  <div class="theme-sec"><h4>🎯 弹动力度 <span class="val-tag" id="bounce-val">100%</span></h4><div class="slider-row"><input type="range" min="0" max="200" value="100" id="bounce-slider" oninput="changeBounce(this.value)"></div></div>
  <div class="theme-sec"><h4>📦 互动效果</h4>
   <div class="fx-row"><div class="fx-label"><span class="ico">✨</span>光影追踪</div><div class="fx-tog on" data-fx="lightTrail" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">🧲</span>磁吸按钮</div><div class="fx-tog on" data-fx="magnetic" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">🃏</span>3D 倾斜</div><div class="fx-tog on" data-fx="tilt3d" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">💧</span>波纹点击</div><div class="fx-tog on" data-fx="ripple" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">💓</span>呼吸脉冲</div><div class="fx-tog on" data-fx="breathing" onclick="toggleFx(this)"></div></div>
  </div>
  <div class="theme-sec"><h4>🌃 背景效果</h4>
   <div class="fx-row"><div class="fx-label"><span class="ico">✨</span>粒子场</div><div class="fx-tog on" data-fx="particles" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">🌌</span>极光流体</div><div class="fx-tog on" data-fx="aurora" onclick="toggleFx(this)"></div></div>
   <div class="fx-row"><div class="fx-label"><span class="ico">🌀</span>波浪层</div><div class="fx-tog on" data-fx="waves" onclick="toggleFx(this)"></div></div>
  </div>
  <div class="conflict-warn" id="conflict-warn"><span class="warn-ico">⚠️</span><span id="conflict-text"></span></div>
  <div style="display:flex;gap:10px;margin-top:12px"><button class="btn" style="flex:1" onclick="resetAll()">恢复默认</button><button class="btn btn-primary" style="flex:1" onclick="saveAll()">保存</button></div>
</div>

<!-- 搜索浮动面板 -->
<div class="search-float" id="search-p"><span class="search-icon">🔍</span><input placeholder="搜索..." onkeydown="if(event.key==='Enter')doSearch(this.value)" autocomplete="off"><div class="search-history" id="search-history"></div></div>

<!-- 安全角落 -->
<div class="safe-dot" id="safe-dot"><span class="dot"></span>安全模式</div>

<div class="container">
  <h1>👋 欢迎使用 PixivFavSearch</h1>
  <p class="subtitle">首次使用需要登录 Pixiv 以获取收藏数据<br>请选择你的登录方式</p>

  <div id="status" class="status">
    <span class="spinner"></span><span id="status-text"></span>
  </div>

  <button class="option" id="btn-edge" onclick="grabEdge()">
    <span class="icon">🌐</span>
    <div class="label">方式 A：我已用 Edge 登录 Pixiv（推荐）</div>
    <div class="desc">一键读取浏览器登录态，无需额外操作</div>
  </button>

  <button class="option" id="btn-webview" onclick="openWebView()">
    <span class="icon">🔐</span>
    <div class="label">方式 B：现在登录</div>
    <div class="desc">在弹出的窗口中输入 Pixiv 账号密码登录</div>
  </button>

  <div class="tip" id="tip">
    💡 <strong>方式 A（推荐）</strong> 需要 Edge 浏览器已登录 Pixiv 且未关闭，一键读取<br>
    ⚠️ <strong>方式 B</strong> 登录后 cookie <strong>不会持久化</strong>，每次启动都需要重新登录<br>
    💡 强烈建议用方式 A，先打开 Edge 登录 Pixiv 再回来点按钮
  </div>

  <div id="success-area" class="hidden">
    <p style="color:#66ffb2;margin-top:16px;font-size:14px;">✅ 登录成功！uid=<span id="uid"></span>，cookie 已保存</p>
    <button class="btn-primary" onclick="goToMain()">进入主界面 →</button>
  </div>

  <div id="skip-area">
    <button class="btn-skip" onclick="skipFirstRun()">跳过，稍后设置</button>
  </div>
</div>

<script>
function setStatus(text, kind) {
  const el = document.getElementById('status');
  const st = document.getElementById('status-text');
  el.className = 'status ' + (kind || 'info');
  st.textContent = text;
}
function clearStatus() {
  document.getElementById('status').className = 'status';
}

async function grabEdge() {
  const btn = document.getElementById('btn-edge');
  btn.disabled = true;
  setStatus('正在连接 Edge 浏览器...');
  try {
    const r = await fetch('/api/first-run/edge', {method: 'POST'});
    const j = await r.json();
    if (j.ok) {
      showSuccess(j.uid);
    } else {
      setStatus('❌ ' + (j.error || '连接失败，请先用 Edge 登录 Pixiv'), 'error');
      btn.disabled = false;
    }
  } catch(e) {
    setStatus('❌ 网络错误: ' + e.message, 'error');
    btn.disabled = false;
  }
}

async function openWebView() {
  setStatus('正在打开登录窗口...');
  try {
    // 通知后端启动 WebView2 登录窗口
    const r = await fetch('/api/first-run/launch-login', {method: 'POST'});
    const j = await r.json();
    if (j.ok) {
      setStatus('登录窗口已打开，请在弹出的窗口中完成登录，然后点击下方按钮', 'info');
      document.getElementById('tip').innerHTML = '💡 请在弹出的 <strong>PixivFavSearch — 登录 Pixiv</strong> 窗口中完成登录<br>💡 登录完成后回到此处点击下方按钮';
      // 显示抓取按钮
      const grabBtn = document.createElement('button');
      grabBtn.className = 'btn-primary';
      grabBtn.id = 'btn-webview-grab';
      grabBtn.textContent = '已登录，抓取 Cookie';
      grabBtn.style.marginTop = '16px';
      grabBtn.onclick = grabWebView;
      document.getElementById('tip').appendChild(grabBtn);
    } else {
      setStatus('❌ ' + (j.error || '启动失败'), 'error');
    }
  } catch(e) {
    setStatus('❌ 网络错误: ' + e.message, 'error');
  }
}

async function grabWebView() {
  const btn = document.getElementById('btn-webview-grab') || document.getElementById('btn-webview');
  if (btn) btn.disabled = true;
  setStatus('正在从登录窗口抓取 cookie...');
  try {
    const r = await fetch('/api/first-run/webview', {method: 'POST'});
    const j = await r.json();
    if (j.ok) {
      showSuccess(j.uid);
    } else {
      setStatus('❌ ' + (j.error || '抓取失败，请确认已登录'), 'error');
      if (btn) btn.disabled = false;
    }
  } catch(e) {
    setStatus('❌ 网络错误: ' + e.message, 'error');
    if (btn) btn.disabled = false;
  }
}

function showSuccess(uid) {
  setStatus('✅ 登录成功！Cookie 已保存', 'success');
  document.getElementById('uid').textContent = uid;
  document.getElementById('success-area').classList.remove('hidden');
  document.getElementById('btn-edge').style.display = 'none';
  document.getElementById('btn-webview').style.display = 'none';
  document.getElementById('tip').style.display = 'none';
  document.getElementById('skip-area').style.display = 'none';
}

function goToMain() {
  window.location.href = '/';
}

function skipFirstRun() {
  if (confirm('确定要跳过登录吗？跳过后将无法导入收藏，但可以随时从托盘菜单重新登录。')) {
    window.location.href = '/';
  }
}
</script>

<script>
const fxState={lightTrail:true,magnetic:true,tilt3d:true,ripple:true,breathing:true,particles:true,aurora:true,waves:true,grid:false,nebula:false,contour:false};
const fxIntensity={lightTrail:60,magnetic:50,tilt3d:70,ripple:80,breathing:50,particles:60,aurora:50,waves:40};

function toggleTheme(){document.getElementById('theme-panel').classList.toggle('open')}
function toggleFx(el){el.classList.toggle('on');fxState[el.dataset.fx]=el.classList.contains('on');checkConflicts()}
function checkConflicts(){var w=document.getElementById('conflict-warn');var t=document.getElementById('conflict-text');if(fxState.tilt3d&&fxState.magnetic){w.classList.add('show');t.textContent='3D倾斜与磁吸冲突'}else{w.classList.remove('show')}}
function changeBounce(v){document.getElementById('bounce-val').textContent=v+'%';var y2=(1+v/100*0.8).toFixed(2);document.documentElement.style.setProperty('--ease-bounce','cubic-bezier(.22,'+y2+',.36,1)')}
function applyAccent(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--accent',v);document.documentElement.style.setProperty('--accent-g',v+'80');document.getElementById('pick-accent').value=v}}
function applyBg(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--bg',v);document.body.style.backgroundColor=v;document.getElementById('pick-bg').value=v}}
function handleBg(input){if(input.files&&input.files[0]){var r=new FileReader();r.onload=function(e){var p=document.getElementById('bg-preview');p.classList.add('has-img');p.innerHTML='<img src="'+e.target.result+'"><button class=bg-rm onclick="event.stopPropagation();rmBg()">✕</button>';document.body.style.backgroundImage='url('+e.target.result+')';document.body.style.backgroundSize='cover'};r.readAsDataURL(input.files[0])}}
function rmBg(){var p=document.getElementById('bg-preview');p.classList.remove('has-img');p.innerHTML='<span class=bg-txt>📷 导入图片</span><button class=bg-rm onclick="event.stopPropagation();rmBg()">✕</button>';document.body.style.backgroundImage=''}
function resetAll(){applyAccent('#c77dff');applyBg('#000');rmBg();document.querySelectorAll('.fx-tog').forEach(function(t){t.classList.add('on');fxState[t.dataset.fx]=true});checkConflicts()}
function saveAll(){var b=event.target;b.textContent='已保存';b.style.background='#27ae60';setTimeout(function(){b.textContent='保存';b.style.background=''},1500)}
function renderPresets(){var t=[{a:'#c77dff',b:'#000'},{a:'#4a90d9',b:'#000814'},{a:'#27ae60',b:'#0a1a10'},{a:'#e91e63',b:'#1a0810'},{a:'#f39c12',b:'#1a1008'},{a:'#e74c3c',b:'#1a0808'},{a:'#1abc9c',b:'#081a18'},{a:'#3f51b5',b:'#0a0e28'},{a:'#ff6b6b',b:'#1a0a0a'},{a:'#10b981',b:'#061a14'},{a:'#8b5cf6',b:'#0e0820'},{a:'#eab308',b:'#1a1606'}];document.getElementById('preset-themes').innerHTML=t.map(function(x){return'<div class=color-swatch style=background:'+x.a+' onclick="applyAccent(\''+x.a+'\');applyBg(\''+x.b+'\')"></div>'}).join('')}
function checkForUpdates(){fetch('/api/update/check').then(function(r){return r.json()}).then(function(d){if(d.ok&&d.hasUpdate){document.getElementById('ub-ver').textContent='v'+d.latestVer+' 可用';document.getElementById('ub-cl').textContent=(d.changelog||'').slice(0,60);document.getElementById('update-bar').classList.add('show')}}).catch(function(){})}
function doUpdate(){fetch('/api/update/download',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(function(r){return r.json()}).then(function(d){if(d.ok){alert('下载完成: '+d.path)}else{alert('下载失败: '+d.error)}})}

document.addEventListener('mousemove',function(e){
 if(!fxState.lightTrail)return;
 document.querySelectorAll('.card').forEach(function(card){
  var r=card.getBoundingClientRect();var cx=r.left+r.width/2;var cy=r.top+r.height/2;
  var dx=e.clientX-cx;var dy=e.clientY-cy;var dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<200){card.style.boxShadow='0 '+(-dy*0.05)+'px '+(30-dist*0.1)+'px rgba(199,125,255,'+(0.3*(1-dist/200)*fxIntensity.lightTrail/100)+')'}
  else{card.style.boxShadow=''}
 });
});

document.addEventListener('mousemove',function(e){
 if(!fxState.magnetic)return;
 var strength=fxIntensity.magnetic/100;
 document.querySelectorAll('.card').forEach(function(card){
  var r=card.getBoundingClientRect();var cx=r.left+r.width/2;var cy=r.top+r.height/2;
  var dx=e.clientX-cx;var dy=e.clientY-cy;var dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<120){var force=(120-dist)/120*8*strength;card.querySelectorAll('.card-btn').forEach(function(btn,i){var angle=(i-1)*0.3;btn.style.transform='translate('+Math.cos(angle)*force+'px,'+(Math.sin(angle)*force+force*0.5)+'px)'})}
 });
});

document.addEventListener('mousemove',function(e){
 if(!fxState.tilt3d)return;
 var maxAngle=fxIntensity.tilt3d/100*8;
 document.querySelectorAll('.card').forEach(function(card){
  var r=card.getBoundingClientRect();
  if(e.clientX>r.left&&e.clientX<r.right&&e.clientY>r.top&&e.clientY<r.bottom){
   var px=(e.clientX-r.left)/r.width-0.5;var py=(e.clientY-r.top)/r.height-0.5;
   card.style.transform='perspective(800px) rotateY('+(px*maxAngle)+'deg) rotateX('+(-py*maxAngle)+'deg) translateY(-8px) scale(1.03)';
  }
 });
});

document.addEventListener('click',function(e){
 if(!fxState.ripple)return;
 var ripple=document.createElement('div');
 ripple.style.cssText='position:fixed;left:'+(e.clientX-20)+'px;top:'+(e.clientY-20)+'px;width:40px;height:40px;border-radius:50%;background:radial-gradient(circle,rgba(199,125,255,.4),transparent);pointer-events:none;z-index:9999;animation:rippleExpand .6s ease-out forwards';
 document.body.appendChild(ripple);setTimeout(function(){ripple.remove()},600);
});

var lastMove=Date.now();
document.addEventListener('mousemove',function(){lastMove=Date.now()});
function breathingLoop(){
 if(fxState.breathing&&Date.now()-lastMove>3000){var btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation='breathe 2s ease-in-out infinite'}
 else{var btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation=''}
 requestAnimationFrame(breathingLoop)}breathingLoop();


setTimeout(function(){checkForUpdates();renderPresets()},1500);
</script>
<style>
@keyframes rippleExpand{from{transform:scale(0);opacity:1}to{transform:scale(3);opacity:0}}
@keyframes breathe{0%,100%{box-shadow:0 0 0 rgba(199,125,255,0)}50%{box-shadow:0 0 25px rgba(199,125,255,.5)}}
</style>
</body>
</html>"""

INDEX = r"""<meta charset=utf-8>
<title>PixivFavSearch</title>
<style>

:root{--bg:#000;--glass:rgba(255,255,255,.07);--glass-bd:rgba(255,255,255,.12);--accent:#c77dff;--accent-g:rgba(199,125,255,.5);--txt:#fff;--sub:rgba(255,255,255,.55);--green:#34c759;--ease-power:cubic-bezier(.16,1,.3,1);--ease-punch:cubic-bezier(.22,1.4,.36,1);--ease-snap:cubic-bezier(.34,1.56,.64,1)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'SF Pro Display','PingFang SC',sans-serif;background:var(--bg);color:var(--txt);height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased;transition:background .4s}
body::before{content:'';position:fixed;inset:0;background:radial-gradient(80% 60% at 15% 25%,rgba(100,50,200,.3) 0%,transparent 55%),radial-gradient(70% 90% at 85% 75%,rgba(180,80,220,.2) 0%,transparent 50%);pointer-events:none;z-index:0;transition:background .4s}

/* 安全角落提示 */
.safe-dot{position:fixed;bottom:18px;left:50%;transform:translateX(-50%) translateY(8px);background:var(--glass);backdrop-filter:blur(20px);border:1px solid rgba(52,199,89,.3);border-radius:16px;padding:6px 14px;font-size:11px;color:var(--green);display:flex;align-items:center;gap:6px;opacity:0;pointer-events:none;transition:all .4s var(--ease-power);z-index:50}
.safe-dot.on{opacity:1;transform:translateX(-50%) translateY(0)}
.safe-dot .dot{width:6px;height:6px;border-radius:50%;background:var(--green);box-shadow:0 0 8px var(--green)}

/* 侧边栏 */
.sidebar{position:fixed;left:14px;top:50%;transform:translateY(-50%);width:64px;background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:32px;padding:10px 6px;z-index:100;display:flex;flex-direction:column;gap:6px;box-shadow:0 12px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.15);transition:all .4s var(--ease-power)}
.sidebar:hover{transform:translateY(-50%) scale(1.06);box-shadow:0 20px 60px rgba(0,0,0,.6),0 0 80px color-mix(in srgb,var(--accent) 20%,transparent)}
.sb-item{width:52px;height:52px;border-radius:26px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:22px;color:var(--sub);position:relative;transition:all .35s var(--ease-snap)}
.sb-item:hover{transform:scale(1.22);color:var(--txt);background:rgba(255,255,255,.08)}
.sb-item:active{transform:scale(.88)}
.sb-item.active{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;box-shadow:0 6px 24px var(--accent-g);animation:sbPop .5s var(--ease-punch)}
@keyframes sbPop{0%{transform:scale(.75)}40%{transform:scale(1.3)}60%{transform:scale(.9)}80%{transform:scale(1.1)}100%{transform:scale(1)}}
.sb-tip{position:absolute;left:62px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--glass-bd);padding:8px 14px;border-radius:14px;font-size:13px;white-space:nowrap;opacity:0;transform:translateX(-10px) scale(.8);pointer-events:none;transition:all .3s var(--ease-snap);box-shadow:0 8px 24px rgba(0,0,0,.5)}
.sb-item:hover .sb-tip{opacity:1;transform:translateX(0) scale(1)}

/* 灵动岛 */
.island{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:10px 22px;display:flex;align-items:center;gap:14px;z-index:200;box-shadow:0 10px 40px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.12);transition:all .5s var(--ease-power)}
.island:hover{padding:10px 28px;box-shadow:0 16px 56px rgba(0,0,0,.6),0 0 80px color-mix(in srgb,var(--accent) 15%,transparent)}
.island-btn{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.06);border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;color:var(--txt);transition:all .3s var(--ease-snap)}
.island-btn:hover{transform:scale(1.25);background:var(--accent);box-shadow:0 6px 20px var(--accent-g)}
.island-btn:active{transform:scale(.85)}
.island-txt{font-size:13px;color:var(--sub)}
.island-txt b{color:var(--txt)}

/* 搜索面板 */
.search-float{position:fixed;top:76px;left:50%;transform:translateX(-50%) scale(.9) translateY(-15px);width:min(500px,88vw);background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:26px;padding:18px 22px;display:flex;align-items:center;gap:14px;z-index:180;opacity:0;pointer-events:none;transition:all .5s var(--ease-punch);box-shadow:0 24px 64px rgba(0,0,0,.6),inset 0 1px 0 rgba(255,255,255,.12)}
.search-float.open{opacity:1;pointer-events:all;transform:translateX(-50%) scale(1) translateY(0)}
.search-float input{flex:1;background:transparent;border:none;color:var(--txt);font-size:17px;font-weight:500;outline:none}
.search-float input::placeholder{color:var(--sub)}

/* 统计面板 */
.stats-overview{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:20px}
.stats-kpi{background:var(--glass);backdrop-filter:blur(30px);border:1px solid var(--glass-bd);border-radius:20px;padding:20px 16px;text-align:center;position:relative;overflow:hidden;transition:transform .3s var(--ease-punch)}
.stats-kpi:hover{transform:translateY(-3px)}
.stats-kpi::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,transparent 40%,rgba(255,255,255,.06));pointer-events:none}
.stats-kpi .v{font-size:30px;font-weight:800;color:var(--txt);letter-spacing:-.5px}
.stats-kpi .l{font-size:12px;color:var(--sub);margin-top:6px;font-weight:500}
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.stats-card{background:var(--glass);backdrop-filter:blur(30px);border:1px solid var(--glass-bd);border-radius:22px;padding:22px}
.stats-card h3{font-size:14px;color:var(--txt);margin-bottom:16px;display:flex;align-items:center;gap:8px;font-weight:600}
.stats-card h3::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--glass-bd),transparent)}
.stats-card.wide{grid-column:1 / -1}
/* 年度柱状图 */
.stats-bars{display:flex;align-items:flex-end;gap:8px;height:150px;padding:12px 4px 0}
.stats-bar-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:6px;min-width:0;cursor:pointer}
.stats-bar-col:hover .stats-bar{filter:brightness(1.3)}
.stats-bar-col:hover .stats-bar-y{color:var(--txt)}
.stats-bar{width:100%;max-width:44px;border-radius:8px 8px 3px 3px;background:linear-gradient(180deg,var(--accent),transparent 160%);transition:height .8s var(--ease-punch),filter .2s}
.stats-bar-y{font-size:10px;color:var(--sub);letter-spacing:.5px}
.stats-bar-n{font-size:10px;color:var(--sub);font-weight:600}
/* 作者排行 */
.stats-list{display:flex;flex-direction:column;gap:2px}
.stats-list .srow{display:flex;align-items:center;gap:12px;padding:8px 12px;border-radius:12px;cursor:pointer;transition:background .15s,transform .15s}
.stats-list .srow:hover{background:rgba(255,255,255,.09);transform:translateX(4px)}
.stats-list .rank{width:24px;font-size:11px;color:var(--sub);text-align:center;font-weight:700;flex-shrink:0}
.stats-list .srow:nth-child(1) .rank{color:#ffd700}
.stats-list .srow:nth-child(2) .rank{color:#c0c0c0}
.stats-list .srow:nth-child(3) .rank{color:#cd7f32}
.stats-list .nm{flex:1;font-size:13px;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stats-list .ct{font-size:11px;color:var(--sub);background:rgba(255,255,255,.07);padding:2px 8px;border-radius:8px;flex-shrink:0}
/* 标签云 */
.stats-tags{display:flex;flex-wrap:wrap;gap:10px 12px;align-content:flex-start;padding:4px 0}
.stats-tag{padding:7px 14px;border-radius:16px;background:rgba(255,255,255,.07);border:1px solid transparent;color:var(--txt);cursor:pointer;transition:all .25s var(--ease-punch);font-weight:500}
.stats-tag:hover{background:var(--accent);border-color:var(--accent);color:#fff;transform:scale(1.1) translateY(-2px);box-shadow:0 8px 20px var(--accent-g)}

/* 图片查看器 */
.viewer{position:fixed;inset:0;z-index:900;display:none;align-items:center;justify-content:center}
.viewer.open{display:flex;animation:viewerIn .3s var(--ease-punch)}
@keyframes viewerIn{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}
.viewer-bg{position:absolute;inset:0;background:rgba(10,10,20,.88);backdrop-filter:blur(24px)}
.viewer-img{position:relative;max-width:92vw;max-height:86vh;object-fit:contain;border-radius:12px;box-shadow:0 32px 96px rgba(0,0,0,.7);cursor:zoom-out;transition:transform .25s var(--ease-punch)}
.viewer-img:hover{transform:scale(1.01)}
.viewer-info{position:absolute;bottom:24px;left:50%;transform:translateX(-50%);max-width:80vw;text-align:center;color:var(--txt);font-size:14px;background:rgba(0,0,0,.45);padding:10px 18px;border-radius:14px;backdrop-filter:blur(12px)}
.viewer-info .vt{font-weight:600}
.viewer-info .va{color:var(--sub);font-size:12px;margin-top:2px}
.viewer-nav{position:absolute;top:50%;transform:translateY(-50%);width:52px;height:52px;border-radius:50%;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.1);color:#fff;font-size:26px;cursor:pointer;backdrop-filter:blur(12px);transition:all .2s var(--ease-punch);display:flex;align-items:center;justify-content:center}
.viewer-nav:hover{background:var(--accent);transform:translateY(-50%) scale(1.12)}
.viewer-prev{left:22px}
.viewer-next{right:22px}
.viewer-close{position:absolute;top:20px;right:22px;width:42px;height:42px;border-radius:50%;border:none;background:rgba(255,255,255,.12);color:#fff;font-size:17px;cursor:pointer;backdrop-filter:blur(12px);transition:all .2s}
.viewer-close:hover{background:#ff5b5b;transform:rotate(90deg) scale(1.08)}
.viewer-count{position:absolute;top:24px;left:24px;color:rgba(255,255,255,.75);font-size:13px;background:rgba(0,0,0,.4);padding:6px 12px;border-radius:10px;backdrop-filter:blur(8px)}

/* 搜索历史下拉 */
.search-history{position:absolute;top:calc(100% + 8px);left:0;right:0;background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:18px;padding:8px;display:none;max-height:280px;overflow-y:auto;box-shadow:0 16px 48px rgba(0,0,0,.5);z-index:190}
.search-history.show{display:block;animation:histPop .35s var(--ease-punch)}
@keyframes histPop{from{opacity:0;transform:translateY(-8px) scale(.97)}to{opacity:1;transform:translateY(0) scale(1)}}
.sh-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:12px;cursor:pointer;color:var(--txt);font-size:14px;transition:background .15s}
.sh-item:hover,.sh-item.sel{background:rgba(255,255,255,.12)}
.sh-item .sh-txt{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sh-item .sh-del{opacity:0;color:var(--sub);font-size:12px;padding:2px 6px;border-radius:8px;transition:opacity .15s}
.sh-item:hover .sh-del{opacity:1}
.sh-item .sh-del:hover{color:#ff6b6b}
.sh-empty{padding:12px;color:var(--sub);font-size:13px;text-align:center}
.sh-clear{margin-top:4px;padding:8px;text-align:center;color:var(--sub);font-size:12px;cursor:pointer;border-radius:10px}
.sh-clear:hover{background:rgba(255,255,255,.08);color:#ff6b6b}

/* 主内容 */
.main{position:fixed;top:0;left:92px;right:0;bottom:0;overflow:hidden;padding:24px 32px}
.page{position:absolute;top:0;left:0;right:0;bottom:0;padding:24px 32px;overflow-y:auto;opacity:0;transform:translateX(20px);transition:opacity .4s var(--ease-power),transform .4s var(--ease-power);pointer-events:none}
.page.active{opacity:1;transform:translateX(0);pointer-events:auto;z-index:2}
.page.exit{opacity:0;transform:translateX(-20px);pointer-events:none;z-index:1}

/* 进度条 */
.progress{position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,var(--accent),#e0aaff);width:0;z-index:9999;transition:width .3s;box-shadow:0 0 20px var(--accent-g)}
.progress.active{width:100%;transition:width 8s ease-out}

/* 卡片 */
.masonry{columns:4;column-gap:14px;padding-top:64px;max-width:1400px;margin:0 auto}
@media(max-width:1400px){.masonry{columns:3}}
@media(max-width:1100px){.masonry{columns:3}}
@media(max-width:800px){.masonry{columns:2}}

.card{break-inside:avoid;margin-bottom:16px;border-radius:20px;overflow:hidden;position:relative;cursor:pointer;background:var(--glass);backdrop-filter:blur(16px);border:1px solid var(--glass-bd);animation:cardIn .6s var(--ease-punch) both;transition:all .4s var(--ease-snap)}
@keyframes cardIn{from{opacity:0;transform:translateY(30px) scale(.85)}to{opacity:1;transform:translateY(0) scale(1)}}
.card:nth-child(1){animation-delay:0ms}.card:nth-child(2){animation-delay:40ms}.card:nth-child(3){animation-delay:80ms}.card:nth-child(4){animation-delay:120ms}.card:nth-child(5){animation-delay:160ms}.card:nth-child(6){animation-delay:200ms}.card:nth-child(7){animation-delay:240ms}.card:nth-child(8){animation-delay:280ms}.card:nth-child(9){animation-delay:320ms}.card:nth-child(10){animation-delay:360ms}.card:nth-child(11){animation-delay:400ms}.card:nth-child(12){animation-delay:440ms}

.card:hover{transform:translateY(-8px) scale(1.04);box-shadow:0 20px 48px rgba(0,0,0,.5),0 0 40px color-mix(in srgb,var(--accent) 15%,transparent),inset 0 1px 0 rgba(255,255,255,.2);border-color:rgba(255,255,255,.25)}
.card:active{transform:scale(.95);transition-duration:.15s}
.card-img{width:100%;display:block;transition:transform .45s var(--ease-snap);object-fit:cover;max-height:280px}
.card:hover .card-img{transform:scale(1.06)}
.card-ov{position:absolute;inset:0;background:linear-gradient(to top,rgba(0,0,0,.9) 0%,transparent 50%);opacity:0;transition:opacity .3s;display:flex;flex-direction:column;justify-content:flex-end;padding:16px}
.card:hover .card-ov{opacity:1}
.card-tt{font-size:13px;font-weight:600;line-height:1.3;transform:translateY(8px);transition:transform .35s var(--ease-snap)}
.card:hover .card-tt{transform:translateY(0)}
.card-au{font-size:11px;color:var(--sub);margin-top:3px;transform:translateY(8px);transition:transform .35s var(--ease-snap) .04s}
.card:hover .card-au{transform:translateY(0)}
.card-act{display:flex;gap:7px;margin-top:10px}
.card-btn{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.1);backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.1);display:flex;align-items:center;justify-content:center;font-size:14px;color:#fff;opacity:0;transform:translateY(10px);transition:all .3s var(--ease-snap)}
.card:hover .card-btn{opacity:1;transform:translateY(0)}
.card-btn:nth-child(2){transition-delay:.06s}
.card-btn:nth-child(3){transition-delay:.12s}
.card-btn:hover{background:var(--accent);transform:scale(1.3);box-shadow:0 6px 20px var(--accent-g)}
.card-btn:active{transform:scale(.85)}
.card-btn.liked{background:#ff3b30;animation:heartBeat .6s var(--ease-punch)}
@keyframes heartBeat{0%{transform:scale(1)}25%{transform:scale(1.5)}45%{transform:scale(.85)}65%{transform:scale(1.25)}85%{transform:scale(.95)}100%{transform:scale(1)}}

/* 标签弹窗 */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.55);backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;pointer-events:none;transition:opacity .3s}
.modal-bg.open{opacity:1;pointer-events:all}
.modal-box{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:26px;padding:26px;min-width:320px;transform:scale(.85) translateY(16px);transition:transform .45s var(--ease-punch);box-shadow:0 28px 72px rgba(0,0,0,.6)}
.modal-bg.open .modal-box{transform:scale(1) translateY(0)}
.modal-box h3{font-size:16px;margin-bottom:16px;color:var(--accent)}
.tag-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.tag-chip{padding:7px 14px;border-radius:20px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);font-size:13px;cursor:pointer;transition:all .25s var(--ease-snap)}
.tag-chip:hover{background:color-mix(in srgb,var(--accent) 18%,transparent);transform:scale(1.1)}
.tag-chip.on{background:var(--accent);color:#1a0a2e;font-weight:600}
.tag-input{width:100%;padding:12px 16px;border-radius:14px;background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);color:var(--txt);font-size:14px;outline:none;transition:all .25s}
.tag-input:focus{border-color:var(--accent);background:rgba(255,255,255,.08)}

/* 收藏夹 */
.fav-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-top:64px}
.fav-top h2{font-size:21px;font-weight:600}
.fav-add{padding:10px 20px;border-radius:14px;background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;border:none;font-size:14px;font-weight:600;cursor:pointer;transition:all .3s var(--ease-snap);box-shadow:0 4px 20px var(--accent-g)}
.fav-add:hover{transform:scale(1.1) translateY(-2px);box-shadow:0 8px 28px var(--accent-g)}
.fav-add:active{transform:scale(.92)}
.fav-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:20px}
.fav-card{aspect-ratio:3/2;border-radius:20px;overflow:hidden;position:relative;cursor:pointer;transition:all .45s var(--ease-snap);border:1px solid var(--glass-bd)}
.fav-card:hover{transform:scale(1.1) translateY(-10px);box-shadow:0 28px 72px rgba(0,0,0,.7)}
.fav-card-bg{position:absolute;inset:0;transition:transform .5s var(--ease-snap)}
.fav-card:hover .fav-card-bg{transform:scale(1.15)}
.fav-card-info{position:absolute;bottom:0;left:0;right:0;padding:16px;background:linear-gradient(to top,rgba(0,0,0,.85),transparent)}
.fav-card-name{font-size:14px;font-weight:600}
.fav-card-count{font-size:11px;color:var(--sub);margin-top:3px}
.back-btn{display:inline-flex;align-items:center;gap:8px;padding:8px 16px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);color:var(--txt);font-size:14px;cursor:pointer;transition:all .3s var(--ease-snap);margin-bottom:20px}
.back-btn:hover{background:rgba(255,255,255,.1);transform:translateX(-6px)}
.back-btn:active{transform:scale(.95)}

/* 设置 */
.sec{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:22px;margin-bottom:18px;transition:all .35s var(--ease-power);box-shadow:0 8px 32px rgba(0,0,0,.3)}
.sec:hover{transform:translateX(6px)}
.sec h3{font-size:15px;color:var(--accent);margin-bottom:16px;display:flex;align-items:center;gap:8px}
.set-row{display:flex;justify-content:space-between;align-items:center;padding:14px 0;border-bottom:1px solid rgba(255,255,255,.05)}
.set-row:last-child{border-bottom:none}
.set-label{font-size:14px;font-weight:500}
.set-desc{font-size:11px;color:var(--sub);margin-top:3px}
.set-input{padding:10px 14px;border-radius:12px;background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;width:220px;outline:none;transition:all .25s}
.set-input:focus{border-color:var(--accent);background:rgba(255,255,255,.08)}
.tog{width:52px;height:32px;border-radius:16px;background:rgba(255,255,255,.12);position:relative;cursor:pointer;transition:background .35s var(--ease-power)}
.tog.on{background:var(--green)}
.tog::after{content:'';position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;transition:transform .4s var(--ease-punch);box-shadow:0 2px 8px rgba(0,0,0,.3)}
.tog.on::after{transform:translateX(20px)}
.btn{padding:10px 20px;border-radius:12px;background:rgba(255,255,255,.05);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;cursor:pointer;transition:all .3s var(--ease-snap)}
.btn:hover{background:rgba(255,255,255,.12);transform:translateY(-2px)}
.btn:active{transform:scale(.94)}
.btn-red{border-color:rgba(255,80,80,.3);color:#ff6b6b}
.btn-red:hover{background:rgba(255,80,80,.15)}
.btn-primary{background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 70%,#7b2cbf));color:#fff;border:none;font-weight:600}
.btn-primary:hover{box-shadow:0 8px 24px var(--accent-g)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:22px}
.stat{background:var(--glass);backdrop-filter:blur(40px) saturate(180%);border:1px solid var(--glass-bd);border-radius:22px;padding:22px;text-align:center;transition:all .4s var(--ease-snap)}
.stat:hover{transform:translateY(-6px) scale(1.04);box-shadow:0 16px 48px rgba(0,0,0,.4)}
.stat-v{font-size:32px;font-weight:700;color:var(--accent)}
.stat-l{font-size:12px;color:var(--sub);margin-top:6px}

/* 主题面板 (大) */
.theme-panel{position:fixed;top:0;right:-480px;width:460px;height:100vh;background:rgba(15,10,25,.96);backdrop-filter:blur(40px);border-left:1px solid var(--glass-bd);z-index:9999;padding:24px 20px;overflow-y:auto;transition:right .5s var(--ease-punch);box-shadow:-16px 0 48px rgba(0,0,0,.5)}
.theme-panel.open{right:0}
.theme-hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.theme-hdr h2{font-size:17px}
.theme-close{width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,.08);border:none;color:var(--txt);cursor:pointer;transition:all .25s var(--ease-snap);display:flex;align-items:center;justify-content:center}
.theme-close:hover{background:rgba(255,255,255,.15);transform:scale(1.15)}
.theme-close:active{transform:scale(.9)}
.theme-sec{background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);border-radius:16px;padding:16px;margin-bottom:14px}
.theme-sec h4{font-size:13px;color:var(--accent);margin-bottom:14px;display:flex;align-items:center;gap:8px}
.color-grid{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.color-swatch{aspect-ratio:1;border-radius:12px;cursor:pointer;transition:all .25s var(--ease-snap);border:2px solid transparent;position:relative}
.color-swatch:hover{transform:scale(1.2)}
.color-swatch.on{border-color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.4)}
.color-swatch.on::after{content:'✓';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:14px;color:#fff;text-shadow:0 1px 3px rgba(0,0,0,.5)}
.custom-row{display:flex;gap:10px;align-items:center}
.color-picker{width:40px;height:40px;border-radius:10px;border:2px solid var(--glass-bd);cursor:pointer;overflow:hidden;transition:transform .2s}
.color-picker:hover{transform:scale(1.1)}
.color-picker input{width:150%;height:150%;margin:-25%;border:none;cursor:pointer}
.bg-preview{width:100%;height:70px;border-radius:12px;background:rgba(255,255,255,.04);border:2px dashed var(--glass-bd);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all .3s;overflow:hidden;position:relative}
.bg-preview:hover{border-color:var(--accent);background:rgba(255,255,255,.06)}
.bg-preview.has-img{border-style:solid}
.bg-preview img{width:100%;height:100%;object-fit:cover}
.bg-txt{font-size:11px;color:var(--sub);text-align:center}
.bg-rm{position:absolute;top:5px;right:5px;width:20px;height:20px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;border:none;cursor:pointer;font-size:10px;opacity:0;transition:opacity .2s}
.bg-preview:hover .bg-rm{opacity:1}

/* 拉条 */
.slider-row{padding:8px 0}
.slider-row .labels{display:flex;justify-content:space-between;font-size:10px;color:var(--sub);margin-bottom:6px}
.slider-row .labels .rec{color:var(--accent);font-weight:600}
.val-tag{display:inline-block;padding:2px 8px;border-radius:8px;background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);font-size:11px;font-weight:600;min-width:32px;text-align:center}
input[type=range]{-webkit-appearance:none;width:100%;height:5px;border-radius:3px;background:rgba(255,255,255,.08);outline:none}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4);transition:transform .2s var(--ease-snap)}
input[type=range]::-webkit-slider-thumb:active{transform:scale(1.1)}
.rec-tag{color:var(--accent);font-weight:600;font-size:11px}
.rec-mark{position:absolute;top:20px;width:2px;height:8px;background:var(--accent);transform:translateX(-50%);border-radius:1px;pointer-events:none}

/* 冲突警告 */
.conflict-warn{background:rgba(255,152,0,.12);border:1px solid rgba(255,152,0,.3);border-radius:12px;padding:10px 14px;margin-top:10px;font-size:11px;color:#ff9800;display:none;align-items:center;gap:8px}
.conflict-warn.show{display:flex}
.conflict-warn .warn-ico{font-size:16px}

/* 开关行 */
.fx-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.03)}
.fx-row:last-child{border-bottom:none}
.fx-label{display:flex;align-items:center;gap:8px;font-size:13px}
.fx-label .ico{font-size:16px}
.fx-tog{width:44px;height:26px;border-radius:13px;background:rgba(255,255,255,.1);position:relative;cursor:pointer;transition:background .3s var(--ease-power)}
.fx-tog.on{background:var(--accent)}
.fx-tog::after{content:'';position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:transform .35s var(--ease-punch);box-shadow:0 2px 6px rgba(0,0,0,.3)}
.fx-tog.on::after{transform:translateX(18px)}

::-webkit-scrollbar{width:10px}
::-webkit-scrollbar-track{background:rgba(255,255,255,.04);border-radius:6px}
::-webkit-scrollbar-thumb{background:rgba(199,125,255,.45);border-radius:6px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:rgba(199,125,255,.85);border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:active{background:var(--accent);border:2px solid transparent;background-clip:content-box}

.pagination{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);display:none;justify-content:center;align-items:center;gap:8px;padding:10px 18px;flex-wrap:wrap;background:var(--glass);backdrop-filter:blur(30px) saturate(180%);border:1px solid var(--glass-bd);border-radius:20px;z-index:150;box-shadow:0 12px 40px rgba(0,0,0,.45)}
.pagination.show{display:flex}
.page-btn{padding:8px 16px;border-radius:10px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;font-weight:600;cursor:pointer;transition:all .3s var(--ease-snap)}
.page-btn:hover{transform:scale(1.08);border-color:var(--accent)}
.page-btn:active{transform:scale(.92)}
.page-btn:disabled{opacity:.35;cursor:not-allowed;transform:none}
.page-info{font-size:13px;color:var(--sub);min-width:80px;text-align:center}
.page-info b{color:var(--accent)}
.page-input{width:50px;padding:4px 8px;border-radius:8px;background:rgba(255,255,255,.04);border:1px solid var(--glass-bd);color:var(--txt);font-size:13px;text-align:center;outline:none}
.page-input:focus{border-color:var(--accent)}
.bg-br-row{padding:8px 0}
.bg-br-bar{-webkit-appearance:none;width:100%;height:5px;border-radius:3px;background:rgba(255,255,255,.08);outline:none}
.bg-br-bar::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:var(--accent);cursor:pointer;border:2px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,.4)}
.brightness-overlay{position:fixed;inset:0;background:#000;pointer-events:none;z-index:1;opacity:0;transition:opacity .3s}
.tag-bar{position:fixed;top:140px;left:50%;transform:translateX(-50%);width:min(600px,92vw);display:flex;align-items:center;gap:10px;z-index:185;opacity:0;pointer-events:none;transition:all .4s var(--ease-power)}
.tag-bar.open{opacity:1;pointer-events:all}
.tag-bar-scroll{flex:1;display:flex;gap:8px;overflow-x:auto;padding:8px 0;scrollbar-width:none}
.tag-bar-scroll::-webkit-scrollbar{display:none}
.tag-pill{padding:6px 14px;border-radius:16px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--glass-bd);font-size:12px;color:var(--sub);cursor:pointer;white-space:nowrap;transition:all .3s var(--ease-snap)}
.tag-pill:hover{border-color:var(--accent);color:var(--txt);transform:scale(1.05)}
.tag-pill.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.tag-bar-select select{padding:6px 12px;border-radius:12px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--glass-bd);color:var(--txt);font-size:12px;outline:none;cursor:pointer}
.tag-bar-select select option{background:#1a1a2e;color:var(--txt)}

</style>
<div class="safe-dot" id="safe-dot"><span class="dot"></span>安全模式</div>
<div class="progress" id="prog"></div>

<!-- 灵动岛 -->
<div class="island">
  <button class="island-btn" onclick="togSearch()">🔍</button>
  <span class="island-txt"><b>PixivFavSearch</b> · <span id="island-count">0</span> 幅</span>
  <button class="island-btn" id="refresh-btn" onclick="refreshAll()" title="刷新 (F5)">🔄</button>
  <button class="island-btn" onclick="doImport()">📥</button>
  <button class="island-btn" onclick="togTheme()" title="主题 & 动效">🎨</button>
</div>

<!-- 侧边栏 -->
<nav class="sidebar">
  <div class="sb-item active" onclick="go('search')"><span class="sb-ico">🔍</span><span class="sb-tip">搜索</span></div>
  <div class="sb-item" onclick="go('fav')"><span class="sb-ico">⭐</span><span class="sb-tip">收藏夹</span></div>
  <div class="sb-item" onclick="go('stats')"><span class="sb-ico">📊</span><span class="sb-tip">统计</span></div>
  <div class="sb-item" onclick="go('settings')"><span class="sb-ico">⚙️</span><span class="sb-tip">设置</span></div>
</nav>

<main class="main">
  <div class="page active" id="pg-search"><div class="masonry" id="wall"></div>
</div>
  <div class="page" id="pg-fav">
    <div class="fav-top"><h2>⭐ 收藏夹</h2><button class="fav-add" onclick="newFolder()">+ 新建</button></div>
    <div class="fav-grid" id="fav-grid"></div>
  </div>
  <div class="page" id="pg-fav-inner">
    <button class="back-btn" onclick="go('fav')">← 返回</button>
    <h2 style="margin-bottom:20px" id="inner-title"></h2>
    <div class="masonry" id="inner-wall"></div>
  </div>
  <div class="page" id="pg-stats">
    <h2 style="margin-bottom:18px">📊 收藏统计</h2>
    <div class="stats-overview" id="stats-overview"></div>
    <div class="stats-grid">
      <div class="stats-card wide">
        <h3>📈 年度收藏趋势 <span style="font-weight:400;color:var(--sub);font-size:11px;margin-left:auto">点击柱子筛选该年份</span></h3>
        <div class="stats-bars" id="stats-years"></div>
      </div>
      <div class="stats-card">
        <h3>🥇 作者排行 <span style="font-weight:400;color:var(--sub);font-size:11px;margin-left:auto">点击查看该作者</span></h3>
        <div class="stats-list" id="stats-authors"></div>
      </div>
      <div class="stats-card">
        <h3>🏷️ 热门标签 <span style="font-weight:400;color:var(--sub);font-size:11px;margin-left:auto">点击筛选该标签</span></h3>
        <div class="stats-tags" id="stats-tags"></div>
      </div>
    </div>
  </div>
  <div class="page" id="pg-settings">
    <div class="stats">
      <div class="stat"><div class="stat-v">8,237</div><div class="stat-l">收藏作品</div></div>
      <div class="stat"><div class="stat-v">12</div><div class="stat-l">收藏夹</div></div>
      <div class="stat"><div class="stat-v">v1.0</div><div class="stat-l">版本</div></div>
    </div>
    <div class="sec">
      <h3>🛡️ 安全模式</h3>
      <div class="set-row">
        <div><div class="set-label">开启安全模式</div><div class="set-desc">完全隐藏 R18 内容</div></div>
        <div class="tog on" id="safe-tog" onclick="togSafe()"></div>
      </div>
    </div>
    <div class="sec">
      <h3>🔗 链接打开方式</h3>
      <div class="set-row">
        <div><div class="set-label">作品链接用系统浏览器打开</div><div class="set-desc">默认: 常用浏览器打开 + 托盘气泡提示返回；关闭后用应用内窗口(关窗即回)</div></div>
        <div class="tog on" id="open-mode-tog" onclick="togOpenMode(this)"></div>
      </div>
    </div>
    <div class="sec">
      <h3>🖼️ 缩略图预载</h3>
      <div class="set-row">
        <div><div class="set-label">全量下载缩略图</div><div class="set-desc">后台从最新到最旧批量下载，翻页即秒开</div></div>
        <button class="btn btn-primary" id="prefetch-btn" onclick="togglePrefetch()">开始预载</button>
      </div>
      <div id="prefetch-progress" style="display:none;margin-top:12px">
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--sub);margin-bottom:6px">
          <span id="prefetch-stat">准备中…</span><span id="prefetch-eta"></span>
        </div>
        <div style="height:8px;border-radius:4px;background:rgba(255,255,255,.08);overflow:hidden">
          <div id="prefetch-bar" style="height:100%;width:0%;border-radius:4px;background:linear-gradient(90deg,var(--accent),#e0aaff);transition:width .4s var(--ease-power)"></div>
        </div>
      </div>
    </div>
    <div class="sec">
      <h3>🌐 代理设置</h3>
      <div class="set-row"><div><div class="set-label">HTTP 代理</div><div class="set-desc">连接 Pixiv API</div></div><input class="set-input" value="http://127.0.0.1:10808"></div>
      <div class="set-row"><div><div class="set-label">启用代理</div></div><div class="tog on" onclick="this.classList.toggle('on')"></div></div>
    </div>
    <div class="sec">
      <h3>📥 收藏管理</h3>
      <div class="set-row"><div><div class="set-label">导入/更新收藏</div><div class="set-desc">从 Pixiv 抓取最新收藏</div></div><button class="btn btn-primary" onclick="doImport();togTheme()">导入收藏</button></div>
      <div class="set-row"><div><div class="set-label">搜索</div><div class="set-desc">打开搜索面板</div></div><button class="btn" onclick="togSearch()">打开搜索</button></div>
    </div>
    <div class="sec">
      <h3>🎨 主题 & 动效</h3>
      <div class="set-row"><div><div class="set-label">主题颜色 & 背景</div><div class="set-desc">自定义主色调和背景</div></div><button class="btn" onclick="togTheme()">打开主题面板</button></div>
      <div class="set-row"><div><div class="set-label">弹动力度 & 效果</div><div class="set-desc">调节所有动效强度</div></div><button class="btn" onclick="togTheme()">动效实验室</button></div>
    </div>
    <div class="sec">
      <h3>🔑 Cookie</h3>
      <div class="set-row"><div><div class="set-label">UID 85331620</div><div class="set-desc">17 个 cookie</div></div><button class="btn btn-red">清除并重新登录</button></div>
    </div>
    <div class="sec">
      <h3>💾 数据</h3>
      <div class="set-row"><div><div class="set-label">清空所有收藏</div><div class="set-desc">删除本地全部数据</div></div><button class="btn btn-red">清空</button></div>
    </div>
  </div>
</main>

<!-- 搜索面板 -->
<div class="search-float" id="search-p"><span style="font-size:18px">🔍</span><input placeholder="搜索标题、作者、标签..."></div>
<!-- 标签过滤栏 -->
<div class="tag-bar" id="tag-bar">
  <div class="tag-bar-scroll">
    <span class="tag-pill active" onclick="setTagFilter('',this)">全部</span>
  </div>
  <div class="tag-bar-select">
    <select id="sort-select" onchange="setSortMode(this.value)" title="排序方式">
      <option value="new" selected>🆕 最新收藏</option>
      <option value="relevance">🎯 相关度</option>
      <option value="old">📜 最早收藏</option>
      <option value="author">✍️ 按作者</option>
      <option value="random">🎲 随机</option>
    </select>
  </div>
  <div class="tag-bar-select">
    <select id="coltag-select" onchange="setColtagFilter(this.value)">
      <option value="">全部收藏夹</option>
    </select>
  </div>
</div>
<!-- 亮度遮罩 -->
<div class="brightness-overlay" id="brightness-overlay"></div>

<!-- 分页条(独立于页面容器, 真正固定视口底部; .page 有 transform 会让内部 fixed 失效) -->
<div class="pagination show" id="pagination">
  <button class="page-btn" id="page-first" onclick="goPage(0)">⏮</button>
  <button class="page-btn" id="page-prev" onclick="goPage(currentPage-1)">◀</button>
  <input type="number" class="page-input" id="page-input" value="1" min="1" onchange="goPage(parseInt(this.value)-1)">
  <span class="page-info">/ <b id="page-total">1</b> 页</span>
  <button class="page-btn" id="page-next" onclick="goPage(currentPage+1)">▶</button>
  <button class="page-btn" id="page-last" onclick="goPage(totalPages-1)">⏭</button>
</div>

<!-- 图片查看器 -->
<div class="viewer" id="viewer">
  <div class="viewer-bg" onclick="closeViewer()"></div>
  <img class="viewer-img" id="viewer-img" onclick="closeViewer()">
  <div class="viewer-info" id="viewer-info"></div>
  <button class="viewer-nav viewer-prev" id="viewer-prev" onclick="event.stopPropagation();viewerNav(-1)">‹</button>
  <button class="viewer-nav viewer-next" id="viewer-next" onclick="event.stopPropagation();viewerNav(1)">›</button>
  <button class="viewer-close" onclick="closeViewer()">✕</button>
  <div class="viewer-count" id="viewer-count"></div>
</div>


<!-- 标签弹窗 -->
<div class="modal-bg" id="tag-modal">
  <div class="modal-box">
    <h3>⭐ 加入收藏夹</h3>
    <div class="tag-row">
      <span class="tag-chip on">✨ 精选</span><span class="tag-chip">🎮 游戏</span><span class="tag-chip">🌸 二次元</span><span class="tag-chip on">❤️ 喜欢</span>
    </div>
    <input class="tag-input" placeholder="+ 创建新收藏夹...">
  </div>
</div>

<!-- 主题面板 -->
<div class="theme-panel" id="theme-panel">
  <div class="theme-hdr"><h2>🎨 主题 & 动效</h2><button class="theme-close" onclick="togTheme()">✕</button></div>

  <!-- 基础 -->
  <div class="theme-sec">
    <h4>基础</h4>
    <div class="color-grid" id="preset-themes"></div>
    <div style="margin-top:12px"><div class="custom-row"><div class="color-picker"><input type="color" id="pick-accent" value="#c77dff" onchange="applyAccent(this.value)"></div><input class="set-input" id="txt-accent" value="#c77dff" onchange="applyAccent(this.value)" style="flex:1"></div></div>
    <div style="margin-top:8px"><div class="custom-row"><div class="color-picker"><input type="color" id="pick-bg" value="#000000" onchange="applyBg(this.value)"></div><input class="set-input" id="txt-bg" value="#000000" onchange="applyBg(this.value)" style="flex:1"></div></div>
    <div class="bg-preview" id="bg-preview" onclick="document.getElementById('bg-file').click()"><span class="bg-txt">📷 点击导入图片</span><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button></div>
   <div class="theme-sec"><h4>🔆 屏幕亮度 <span class="val-tag" id="bg-br-val">100%</span></h4><div class="slider-row"><input type="range" min="20" max="100" value="100" class="bg-br-bar" id="bg-br-slider" oninput="changeBgBrightness(this.value)"></div></div>

    <input type="file" id="bg-file" accept="image/*" style="display:none" onchange="handleBg(this)">
  </div>

  <!-- 弹动力度 -->
  <div class="theme-sec">
    <h4>🎯 弹动力度 <span class="val-tag" id="bounce-val">100%</span></h4>
    <div class="slider-row">
      <div class="labels"><span>0%</span><span>100%</span><span>200%</span></div>
      <input type="range" min="0" max="200" value="100" id="bounce-slider" oninput="changeBounce(this.value)">
      <div class="rec-mark" style="left:50%" title="推荐 100%"></div>
    </div>
  </div>

  <!-- 互动效果 -->
  <div class="theme-sec">
    <h4>📦 互动效果</h4>
    <div class="fx-row"><div class="fx-label"><span class="ico">✨</span>光影追踪</div><div class="fx-tog on" data-fx="lightTrail" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">60</span><span>100</span></div><input type="range" min="0" max="100" value="60" id="lightTrail-slider" oninput="document.getElementById('lightTrail-val').textContent=this.value+'%'"><span class="val-tag" id="lightTrail-val" style="float:right;margin-top:-24px">60%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">🧲</span>磁吸按钮</div><div class="fx-tog on" data-fx="magnetic" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">50</span><span>100</span></div><input type="range" min="0" max="100" value="50" id="magnetic-slider" oninput="document.getElementById('magnetic-val').textContent=this.value+'%'"><span class="val-tag" id="magnetic-val" style="float:right;margin-top:-24px">50%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">🃏</span>3D 倾斜</div><div class="fx-tog on" data-fx="tilt3d" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">70</span><span>100</span></div><input type="range" min="0" max="100" value="70" id="tilt3d-slider" oninput="document.getElementById('tilt3d-val').textContent=this.value+'%'"><span class="val-tag" id="tilt3d-val" style="float:right;margin-top:-24px">70%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">💧</span>波纹点击</div><div class="fx-tog on" data-fx="ripple" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">80</span><span>100</span></div><input type="range" min="0" max="100" value="80" id="ripple-slider" oninput="document.getElementById('ripple-val').textContent=this.value+'%'"><span class="val-tag" id="ripple-val" style="float:right;margin-top:-24px">80%</span></div>

    <div class="fx-row"><div class="fx-label"><span class="ico">💓</span>呼吸脉冲</div><div class="fx-tog on" data-fx="breathing" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">50</span><span>100</span></div><input type="range" min="0" max="100" value="50" id="breathing-slider" oninput="document.getElementById('breathing-val').textContent=this.value+'%'"><span class="val-tag" id="breathing-val" style="float:right;margin-top:-24px">50%</span></div>
  </div>

  <!-- 背景效果 -->
  <div class="theme-sec">
    <h4>🌃 背景效果</h4>
    <div class="fx-row"><div class="fx-label"><span class="ico">✨</span>粒子场</div><div class="fx-tog on" data-fx="particles" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">60</span><span>100</span></div><input type="range" min="0" max="100" value="60" id="particles-slider" oninput="document.getElementById('particles-val').textContent=this.value+'%'"><span class="val-tag" id="particles-val" style="float:right;margin-top:-24px">60%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">🌌</span>极光流体</div><div class="fx-tog on" data-fx="aurora" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">50</span><span>100</span></div><input type="range" min="0" max="100" value="50" id="aurora-slider" oninput="document.getElementById('aurora-val').textContent=this.value+'%'"><span class="val-tag" id="aurora-val" style="float:right;margin-top:-24px">50%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">🌀</span>波浪层</div><div class="fx-tog on" data-fx="waves" onclick="toggleFx(this)"></div></div>
    <div class="slider-row"><div class="labels"><span>0</span><span class="rec-tag">40</span><span>100</span></div><input type="range" min="0" max="100" value="40" id="waves-slider" oninput="document.getElementById('waves-val').textContent=this.value+'%'"><span class="val-tag" id="waves-val" style="float:right;margin-top:-24px">40%</span></div>
    
    <div class="fx-row"><div class="fx-label"><span class="ico">🔮</span>呼吸网格</div><div class="fx-tog" data-fx="grid" onclick="toggleFx(this)"></div></div>
    <div class="fx-row"><div class="fx-label"><span class="ico">💫</span>星云雾</div><div class="fx-tog" data-fx="nebula" onclick="toggleFx(this)"></div></div>
    <div class="fx-row"><div class="fx-label"><span class="ico">📊</span>等高线</div><div class="fx-tog" data-fx="contour" onclick="toggleFx(this)"></div></div>
  </div>

  <!-- 冲突警告 -->
  <div class="conflict-warn" id="conflict-warn"><span class="warn-ico">⚠️</span><span id="conflict-text"></span></div>

  <div style="display:flex;gap:10px;margin-top:14px">
    <button class="btn" style="flex:1" onclick="resetAll()">恢复默认</button>
    <button class="btn btn-primary" style="flex:1" onclick="saveAll()">保存</button>
  </div>
  <div id="draft-tip" class="draft-tip"></div>
</div>


<style>
@keyframes rippleExpand{from{transform:scale(0);opacity:1}to{transform:scale(3);opacity:0}}
@keyframes breathe{0%,100%{box-shadow:0 0 0 rgba(199,125,255,0)}50%{box-shadow:0 0 25px rgba(199,125,255,.5)}}
</style>
<script>
let works=[];
let folders=[];
let safe=true;
let searchQuery='';
let tagFilter='';
let coltagFilter='';
let sortMode='new';   // 默认最新收藏(搜索相关度需手动选)
let statsFilter=null;   // 统计面板跳转的精确筛选 {type:'author'|'year'|'tag', val:...}
let currentPage=0;
let pageSize=200;
let totalPages=0;
let totalItems=0;

const fxState={lightTrail:true,magnetic:true,tilt3d:true,ripple:true,breathing:true,particles:true,aurora:true,waves:true,grid:false,nebula:false,contour:false};
const fxIntensity={lightTrail:60,magnetic:50,tilt3d:70,ripple:80,breathing:50,particles:60,aurora:50,waves:40};

const conflicts=[
 {effects:['tilt3d','magnetic'],msg:'3D倾斜与磁吸按钮冲突'},
 {effects:['tilt3d','ripple'],msg:'3D倾斜与波纹点击冲突'},
 {effects:['particles','nebula'],msg:'粒子场与星云雾冲突'},
 {effects:['aurora','waves'],msg:'极光流体与波浪层冲突'}
];

function colorHash(id){
 let h=0;const s=String(id);
 for(let i=0;i<s.length;i++){h=s.charCodeAt(i)+((h<<5)-h);}
 return 'hsl('+(Math.abs(h)%360)+', 60%, 50%)';
}

// 链接打开方式: 'browser'=系统默认浏览器(默认) / 'inner'=应用内窗口(备选)
function getOpenMode(){try{return localStorage.getItem('pfs_open_mode')||'browser'}catch(e){return 'browser'}}
function setOpenMode(m){try{localStorage.setItem('pfs_open_mode',m)}catch(e){}}
function openWork(id){
 const url='https://www.pixiv.net/artworks/'+id;
 const mode=getOpenMode();
 if(mode==='inner'){
  // 备选: 应用内 WebView 窗口(关掉即回主应用)
  window._workWinOpened=false;
  fetch('/api/open-work',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,mode:'inner'})})
   .then(r=>r.json()).then(d=>{if(d&&d.opened)window._workWinOpened=true;})
   .catch(()=>{});
  setTimeout(()=>{if(!window._workWinOpened)window.open(url,'_blank');},600);
 }else{
  // 默认: 系统常用浏览器。走后端(带托盘气泡"点图标返回");
  // 纯浏览器模式(8897直开)后端没注册回调 → opened:false → 前端直接 window.open
  fetch('/api/open-work',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url,mode:'browser'})})
   .then(r=>r.json()).then(d=>{if(!d||!d.opened)window.open(url,'_blank');})
   .catch(()=>{window.open(url,'_blank');});
 }
}

function workCard(w){
 const c=colorHash(w.id);
 const thumbUrl='/thumb/'+w.id;
 const author=w.userName||'Unknown';
 const title=w.title||'Untitled';
 return '<div class="card" data-id="'+w.id+'" onclick="openViewer(\''+w.id+'\')">'+
 '<img class="card-img" src="'+thumbUrl+'" loading="lazy" style="width:100%;max-height:280px;object-fit:cover;background:'+c+';min-height:80px" onerror="this.onerror=null;this.style.background=\'linear-gradient(135deg,'+c+','+c+'dd)\';this.parentElement.style.minHeight=\'80px\'">'+
 '<div class="card-ov"><div class="card-tt">'+title+'</div><div class="card-au">'+author+'</div>'+
 '<div class="card-act"><button class="card-btn" onclick="event.stopPropagation();showTags(\''+w.id+'\')">⭐</button>'+
 '<button class="card-btn" onclick="event.stopPropagation();this.classList.toggle(\'liked\')">❤️</button>'+
 '<button class="card-btn" onclick="event.stopPropagation();openWork(\''+w.id+'\')">🔗</button></div></div></div>';
}

function wallHTML(list){
 let filtered = list.filter(w=>!w.isMasked);
 if(safe) filtered = filtered.filter(w=>!w.isR18);
 return filtered.map(w=>workCard(w)).join('');
}

let _fetchSeq=0;   // 请求序号: 快速翻页时旧响应后到会覆盖新数据, 守卫丢弃过期响应
let _lastGoodPage=0;   // 最后一次成功渲染的页码(请求失败时回滚, 防页码累积飞页)
async function fetchWorks(retry=0){
 const seq=++_fetchSeq;
 const pageAtRequest=currentPage;   // 发请求时的页码
 try{
  const p=new URLSearchParams({mode:'pixiv',q:searchQuery,tag:tagFilter,coltag:coltagFilter,sort:sortMode,offset:currentPage*pageSize,limit:pageSize,safe: safe ? '1' : '0'});
  // 统计面板专用筛选参数
  if(statsFilter){p.set(statsFilter.type,statsFilter.val);}
  const r=await fetch('/api/search?'+p);
  if(!r.ok){throw new Error('HTTP '+r.status)}
  const d=await r.json();
  if(seq!==_fetchSeq){
   // 过期响应(用户已翻到别的页): 数据丢弃, 但分页 UI 仍按当前页刷新
   updatePagination();
   return;
  }
  works=d.items||[];
  totalItems=d.total||0;
  totalPages=Math.max(1,Math.ceil(totalItems/pageSize));
  _lastGoodPage=currentPage;
  updatePagination();
 }catch(e){
  console.log('fetchWorks error',e);
  // 失败重试(最多3次, 间隔递增): 429/瞬时抖动自愈
  if(retry<3&&seq===_fetchSeq){
   setTimeout(()=>{if(seq===_fetchSeq)fetchWorks(retry+1)},400*(retry+1));
   return;
  }
  // 重试仍失败且没有更新的请求: 回滚页码到上次成功页(防连点累积飞页)
  if(seq===_fetchSeq&&currentPage!==_lastGoodPage){
   console.log('翻页失败, 回滚到第'+(_lastGoodPage+1)+'页');
   currentPage=_lastGoodPage;
   updatePagination();
  }
 }
}

async function fetchFavs(){
 try{
  const r=await fetch('/api/coltags');
  const d=await r.json();
  folders=(d.tags||d.data||[]).map(t=>({name:t.tag,count:t.count,color:colorHash(t.tag)}));
 }catch(e){console.log('fetchFavs error',e)}
}

function updatePagination(){
 const totalEl=document.getElementById('page-total');
 const inputEl=document.getElementById('page-input');
 const firstBtn=document.getElementById('page-first');
 const prevBtn=document.getElementById('page-prev');
 const nextBtn=document.getElementById('page-next');
 const lastBtn=document.getElementById('page-last');
 if(totalEl)totalEl.textContent=totalPages;
 if(inputEl)inputEl.value=currentPage+1;
 if(firstBtn)firstBtn.disabled=currentPage<=0;
 if(prevBtn)prevBtn.disabled=currentPage<=0;
 if(nextBtn)nextBtn.disabled=currentPage>=totalPages-1;
 if(lastBtn)lastBtn.disabled=currentPage>=totalPages-1;
}

function goPage(page){
 if(page<0)page=0;
 if(page>=totalPages)page=totalPages-1;
 currentPage=page;
 renderWall();
 // 翻页后回顶: 不然停留在旧滚动位置, 新页内容看着和旧页一样, 像没翻
 const pg=document.getElementById('pg-search');
 if(pg)pg.scrollTop=0;
}

async function renderWall(){
 try{
  await fetchWorks();
  document.getElementById('wall').innerHTML=wallHTML(works);
 }catch(e){
  document.getElementById('wall').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
}

async function renderFavs(){
 try{
  await fetchFavs();
  // 封面缩略图: 拉每个收藏夹的作品, 取最新一张(安全模式下取最新安全图, 没有则渐变兜底)
  const covers = await Promise.all(folders.map(f =>
    fetch('/api/coltags/'+encodeURIComponent(f.name)+'/works?limit=60')
      .then(r=>r.json()).then(d=>{
        const items=(d.items||[]).filter(w=>!w.isMasked&&(!safe||!w.isR18));
        return items.length ? items[0].id : null;   // items 按收藏时间倒序, [0]即最新
      }).catch(()=>null)
  ));
  document.getElementById('fav-grid').innerHTML=folders.map((f,i)=>{
   const cover=covers[i];
   const coverHTML=cover?'<img src="/thumb/'+cover+'" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover" onerror="this.remove()">':'';
   return '<div class="fav-card" onclick="openFav('+i+')"><div class="fav-card-bg" style="background:linear-gradient(135deg,'+f.color+','+f.color+'88)">'+coverHTML+'</div><div class="fav-card-info"><div class="fav-card-name">'+f.name+'</div><div class="fav-card-count">'+f.count+' 幅</div></div></div>';
  }).join('');
 }catch(e){
  document.getElementById('fav-grid').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
}

let pageTransitioning=false;
let _goTimer=null;
function go(targetPage){
 // 目标页(高亮映射用): fav-inner 归到 fav
 const navPage=(targetPage==='fav-inner')?'fav':targetPage;
 const cur=document.querySelector('.page.active');
 const next=document.getElementById('pg-'+targetPage);
 if(!next)return;
 if(cur===next)return;
 // 防卡死: 先把上一轮切换的残留全部清干净(exit 残留会让页面永久透明)
 if(_goTimer){clearTimeout(_goTimer);_goTimer=null;}
 document.querySelectorAll('.page.exit').forEach(p=>p.classList.remove('exit'));
 // 清掉历史遗留的内联 opacity(上次快速切换可能留下)
 document.querySelectorAll('.page').forEach(p=>p.style.opacity='');
 if(cur){
  // 旧页瞬移退出(关 transition 再移除 active, 避免渐隐期盖住新页)
  cur.style.transition='none';
  cur.classList.remove('active');
  void cur.offsetWidth;
  cur.style.transition='';
 }
 // 新页: 先关 transition 瞬移到起点(20px/透明), 强制 reflow, 再开 transition 播放入场动画
 // (旧页不再做 exit 动画: exit 淡出会与新页视觉重叠 → "卡在一半"的观感)
 next.style.transition='none';
 next.classList.add('active');
 void next.offsetWidth;
 next.style.transition='';
 document.querySelectorAll('.sb-item').forEach((s,i)=>{
  const isActive=(navPage==='search'&&i===0)||(navPage==='fav'&&i===1)||(navPage==='stats'&&i===2)||(navPage==='settings'&&i===3);
  if(s.classList.contains('active')!==isActive){
   s.classList.toggle('active');
   if(isActive){
    s.style.animation='none';
    void s.offsetWidth;
    s.style.animation='sbPop .5s var(--ease-punch)';
   }
  }
 });
 pageTransitioning=true;
 _goTimer=setTimeout(()=>{
  document.querySelectorAll('.page.exit').forEach(p=>p.classList.remove('exit'));
  pageTransitioning=false;
  _goTimer=null;
 },400);
 // 分页条只在搜索页显示
 const pagEl=document.getElementById('pagination');
 if(pagEl)pagEl.classList.toggle('show', targetPage==='search');
 if(targetPage==='search'){currentPage=0;renderWall();}
 else if(targetPage==='fav')renderFavs();
 else if(targetPage==='fav-inner')openFav(window.currentFavIdx);
 else if(targetPage==='stats')renderStats();
}

// ===== 统计面板 =====
let statsCache=null;
async function renderStats(){
 try{
  if(!statsCache){
   const r=await fetch('/api/stats');
   statsCache=await r.json();
  }
  const d=statsCache;
  // KPI 行
  const ov=document.getElementById('stats-overview');
  if(ov)ov.innerHTML=
   `<div class="stats-kpi"><div class="v">${d.total.toLocaleString()}</div><div class="l">📚 总收藏</div></div>`+
   `<div class="stats-kpi"><div class="v">${d.safe.toLocaleString()}</div><div class="l">🛡️ 安全作品</div></div>`+
   `<div class="stats-kpi"><div class="v">${d.r18.toLocaleString()}</div><div class="l">🔥 R-18</div></div>`+
   `<div class="stats-kpi"><div class="v">${d.masked.toLocaleString()}</div><div class="l">👻 已失效</div></div>`;
  // 年度趋势(点击→按年份精确筛选)
  const yrs=document.getElementById('stats-years');
  if(yrs&&d.by_year.length){
   const mx=Math.max(...d.by_year.map(y=>y.count));
   yrs.innerHTML=d.by_year.map(y=>
    `<div class="stats-bar-col" title="${y.year}年: ${y.count} 幅" onclick="filterFromStats('year','${y.year}')">`+
    `<div class="stats-bar-n">${y.count}</div>`+
    `<div class="stats-bar" style="height:${Math.max(6,Math.round(y.count/mx*100))}%"></div>`+
    `<div class="stats-bar-y">${y.year.slice(2)}</div></div>`).join('');
  }
  // 作者排行(点击→按作者精确筛选)
  const aus=document.getElementById('stats-authors');
  if(aus&&d.top_authors.length){
   aus.innerHTML=d.top_authors.slice(0,15).map((a,i)=>{
    const nm=a.name.replace(/</g,'&lt;');
    const q=encodeURIComponent(a.name);
    return `<div class="srow" onclick="filterFromStats('author','${q}')">`+
    `<span class="rank">${i+1}</span><span class="nm">${nm}</span><span class="ct">${a.count}</span></div>`;
   }).join('');
  }
  // 标签云(字号按频率, 点击→按标签精确筛选)
  const tgs=document.getElementById('stats-tags');
  if(tgs&&d.top_tags.length){
   const mx=d.top_tags[0].count,mn=d.top_tags[Math.min(29,d.top_tags.length-1)].count;
   tgs.innerHTML=d.top_tags.slice(0,30).map(t=>{
    const sz=Math.round(11+(t.count-mn)/Math.max(1,mx-mn)*10);
    const q=encodeURIComponent(t.tag);
    return `<span class="stats-tag" style="font-size:${sz}px" onclick="filterFromStats('tag','${q}')">${t.tag.replace(/</g,'&lt;')}</span>`;
   }).join('');
  }
 }catch(e){console.log('renderStats error',e)}
}

// 统计跳转: 专用精确筛选(不走搜索框模糊匹配)
// type: 'author' | 'year' | 'tag';  val: 已 encodeURIComponent 的值
function filterFromStats(type,val){
 // 清掉搜索词, 走专用参数
 searchQuery='';
 const input=document.querySelector('.search-float input');
 if(input)input.value='';
 tagFilter='';coltagFilter='';
 currentPage=0;
 statsFilter={type:type,val:decodeURIComponent(val)};
 renderWall();
}

// ===== 图片查看器 =====
let viewerList=[];   // 当前查看的作品列表
let viewerIdx=0;     // 当前索引
function openViewer(id){
 // 在当前 works 里找(也支持 inner-wall)
 const src=works&&works.length?works:[];
 viewerList=src.filter(w=>!w.isMasked&&(!safe||!w.isR18));
 viewerIdx=viewerList.findIndex(w=>w.id===id);
 if(viewerIdx<0)return;
 const v=document.getElementById('viewer');
 if(v)v.classList.add('open');
 showViewerItem();
}
function showViewerItem(){
 const w=viewerList[viewerIdx];
 if(!w)return;
 const img=document.getElementById('viewer-img');
 const info=document.getElementById('viewer-info');
 const cnt=document.getElementById('viewer-count');
 // 大图: origUrl 是 250x250 缩略图, 替换成大图尺寸路径
 let big=(w.origUrl||'').replace('/c/250x250_80_a2/','/c/1200x1200/');
 if(!big)big='/thumb/'+w.id;
 if(img){img.src=big;img.onerror=function(){this.onerror=null;this.src='/thumb/'+w.id;};}
 if(info)info.innerHTML='<div class="vt">'+(w.title||'').replace(/</g,'&lt;')+'</div><div class="va">'+(w.userName||'').replace(/</g,'&lt;')+' · '+(w.pageCount||1)+'P</div>';
 if(cnt)cnt.textContent=(viewerIdx+1)+' / '+viewerList.length;
 const prev=document.getElementById('viewer-prev');
 const next=document.getElementById('viewer-next');
 if(prev)prev.style.display=viewerIdx>0?'flex':'none';
 if(next)next.style.display=viewerIdx<viewerList.length-1?'flex':'none';
}
function viewerNav(dir){
 const ni=viewerIdx+dir;
 if(ni<0||ni>=viewerList.length)return;
 viewerIdx=ni;
 showViewerItem();
}
function closeViewer(){
 const v=document.getElementById('viewer');
 if(v)v.classList.remove('open');
}

async function openFav(idx){
 window.currentFavIdx=idx;
 const f=folders[idx];
 if(!f)return;
 document.getElementById('inner-title').textContent=f.name;
 try{
  const r=await fetch('/api/coltags/'+encodeURIComponent(f.name)+'/works');
  const d=await r.json();
  const items=d.items||[];
  document.getElementById('inner-wall').innerHTML=wallHTML(items);
 }catch(e){
  document.getElementById('inner-wall').innerHTML='<div style="padding:40px;color:var(--sub)">加载失败</div>';
 }
 go('fav-inner');   // 页面 id 是 pg-fav-inner, 不是 pg-inner!
}

// ===== 刷新(灵动岛🔄/F5): 重渲染当前页 + 强制重载图片 =====
async function refreshAll(){
 // 旋转动画
 const btn=document.getElementById('refresh-btn');
 if(btn){
  btn.style.transition='transform .6s cubic-bezier(.22,1.4,.36,1)';
  btn.style.transform='rotate(360deg)';
  setTimeout(()=>{btn.style.transition='none';btn.style.transform='rotate(0deg)';void btn.offsetWidth;btn.style.transition='';},650);
 }
 // 清统计缓存(收藏数变化后统计也要新)
 statsCache=null;
 // 找当前页重渲染
 const cur=document.querySelector('.page.active');
 const page=cur?cur.id.replace('pg-',''):null;
 if(page==='search'){
  await fetchWorks();
  document.getElementById('wall').innerHTML=wallHTML(works);
 }else if(page==='fav'){
  await fetchFavs();
  renderFavs();
 }else if(page==='fav-inner'){
  openFav(window.currentFavIdx);
 }else if(page==='stats'){
  renderStats();
 }
 // 强制重载当前页所有缩略图(绕过缓存: 加时间戳查询参数)
 // 场景: 预载刚下完/占位图被真图替换, img 标签还挂着旧地址
 document.querySelectorAll('.page.active img').forEach(img=>{
  const src=img.getAttribute('src')||'';
  if(src.startsWith('/thumb/')){
   const base=src.split('?')[0];
   img.src=base+'?v='+Date.now();
  }
 });
 // 灵动岛计数也更新
 try{
  const st=await fetch('/api/thumb-prefetch/status').then(r=>r.json());
  const cnt=document.getElementById('island-count');
  if(cnt)cnt.textContent=(st.cached>=0?st.cached:0).toLocaleString();
 }catch(e){}
}

function togSearch(){
 const p=document.getElementById('search-p');
 const tb=document.getElementById('tag-bar');
 p.classList.toggle('open');
 tb.classList.toggle('open');
 if(p.classList.contains('open'))p.querySelector('input').focus();
}

document.addEventListener('DOMContentLoaded',function(){
 const input=document.querySelector('.search-float input');
 if(input){
  let _searchDebounce=null;
  input.addEventListener('input',function(){
   searchQuery=this.value.trim();
   if(searchQuery)statsFilter=null;   // 用户主动输入搜索词时清掉统计筛选
   // 防抖 250ms: 打字过程不发请求(防 429 限流), 停顿才搜
   clearTimeout(_searchDebounce);
   _searchDebounce=setTimeout(()=>renderWall(),250);
  });
  input.addEventListener('keydown',function(e){
   if(e.key==='Enter'){searchQuery=this.value.trim();if(searchQuery)statsFilter=null;renderWall();addSearchHistory(searchQuery);hideSearchHistory();}
  });
  // ---- 搜索历史: 聚焦显示 / 失焦隐藏 / ↑↓选择 / 点击回填 ----
  input.addEventListener('focus',function(){showSearchHistory();});
  document.addEventListener('mousedown',function(e){
   const sf=document.getElementById('search-p');
   if(sf&&!sf.contains(e.target))hideSearchHistory();
  });
 }
});

// ===== 搜索历史 (localStorage, 最近 20 条) =====
const SH_KEY='pfs_search_history';
const SH_MAX=20;
let shSelIdx=-1;
function getSearchHistory(){
 try{return JSON.parse(localStorage.getItem(SH_KEY)||'[]');}catch(e){return[];}
}
function addSearchHistory(q){
 if(!q)return;
 let h=getSearchHistory().filter(x=>x!==q);
 h.unshift(q);h=h.slice(0,SH_MAX);
 try{localStorage.setItem(SH_KEY,JSON.stringify(h));}catch(e){}
}
function removeSearchHistory(q){
 let h=getSearchHistory().filter(x=>x!==q);
 try{localStorage.setItem(SH_KEY,JSON.stringify(h));}catch(e){}
 renderSearchHistory();
}
function clearSearchHistory(){
 try{localStorage.removeItem(SH_KEY);}catch(e){}
 hideSearchHistory();
}
function renderSearchHistory(){
 const box=document.getElementById('search-history');
 if(!box)return;
 const h=getSearchHistory();
 if(!h.length){box.innerHTML='<div class="sh-empty">暂无搜索记录</div>';return;}
 box.innerHTML=h.map((q,i)=>`<div class="sh-item${i===shSelIdx?' sel':''}" data-q="${q.replace(/"/g,'&quot;')}"><span>🕘</span><span class="sh-txt">${q.replace(/</g,'&lt;')}</span><span class="sh-del" data-del="${q.replace(/"/g,'&quot;')}">✕</span></div>`).join('')+'<div class="sh-clear" onclick="clearSearchHistory()">清空全部历史</div>';
 box.querySelectorAll('.sh-item').forEach(el=>{
  el.addEventListener('click',function(ev){
   if(ev.target.classList.contains('sh-del')){ev.stopPropagation();removeSearchHistory(this.dataset.del||ev.target.dataset.del);return;}
   const q=el.dataset.q;const input=document.querySelector('.search-float input');
   if(input){input.value=q;searchQuery=q;renderWall();}
   addSearchHistory(q);hideSearchHistory();
  });
 });
}
function showSearchHistory(){shSelIdx=-1;renderSearchHistory();const box=document.getElementById('search-history');if(box)box.classList.add('show');}
function hideSearchHistory(){const box=document.getElementById('search-history');if(box)box.classList.remove('show');}

// 侧键撤回(X1/X2): 必须在 mousedown 阶段 preventDefault ——
// WebView2 在 mousedown 时触发原生历史后退, 等 mouseup 早就导航走了。
let _sideBtnHandled=0;   // 时间戳: mousedown 处理过, 300ms 内 mouseup 不重复触发
document.addEventListener('mousedown',e=>{
 if(e.button===3||e.button===4){
  e.preventDefault();   // 挡掉 WebView2 原生后退/前进
  e.stopPropagation();
  _sideBtnHandled=Date.now();
  goBack();
 }
},{capture:true});
// mouseup 兜底(仅当 mousedown 被别的层吃掉时才生效)
document.addEventListener('mouseup',e=>{
 if((e.button===3||e.button===4)&&Date.now()-_sideBtnHandled>300){
  goBack();
 }
});

let mouseGestureStart=null;
document.addEventListener('mousedown',e=>{
 if(e.button===2)mouseGestureStart={x:e.clientX,y:e.clientY};
});

document.addEventListener('mousemove',e=>{
 if(!mouseGestureStart)return;
 const dx=e.clientX-mouseGestureStart.x;
 const dy=e.clientY-mouseGestureStart.y;
 if(Math.sqrt(dx*dx+dy*dy)>80){
  goBack();
  mouseGestureStart=null;
 }
});

document.addEventListener('mouseup',e=>{
 if(e.button===2)mouseGestureStart=null;
});

document.addEventListener('contextmenu',e=>e.preventDefault());

// 查看器打开时滚轮切换
document.addEventListener('wheel',e=>{
 const v=document.getElementById('viewer');
 if(!v||!v.classList.contains('open'))return;
 if(e.deltaY>0)viewerNav(1);
 else if(e.deltaY<0)viewerNav(-1);
},{passive:true});

document.addEventListener('keydown',e=>{
 // F5: 应用内刷新(重渲染+图片重载), 不整页 reload
 if(e.key==='F5'){e.preventDefault();refreshAll();return;}
 // 查看器打开时: Esc关闭 / ←→切换 / 滚轮由 wheel 事件处理
 const viewerOpen=document.getElementById('viewer')&&document.getElementById('viewer').classList.contains('open');
 if(viewerOpen){
  if(e.key==='Escape'){closeViewer();return;}
  if(e.key==='ArrowLeft'){viewerNav(-1);return;}
  if(e.key==='ArrowRight'){viewerNav(1);return;}
 }
 if(e.key==='Escape')goBack();
 // Ctrl+F / Ctrl+K: 聚焦搜索框(没打开则先打开)
 if((e.ctrlKey||e.metaKey)&&(e.key==='f'||e.key==='k')){
  e.preventDefault();
  const sp=document.getElementById('search-p');
  if(sp&&!sp.classList.contains('open'))togSearch();
  const inp=document.querySelector('.search-float input');
  if(inp){inp.focus();inp.select();}
  return;
 }
 // 非输入状态下的翻页快捷键: ←/→
 const tag=document.activeElement&&document.activeElement.tagName;
 const inInput=tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT';
 if(!inInput){
  const cur=document.querySelector('.page.active');
  if(cur&&cur.id==='pg-search'){
   if(e.key==='ArrowLeft'&&currentPage>0)goPage(currentPage-1);
   if(e.key==='ArrowRight'&&currentPage<totalPages-1)goPage(currentPage+1);
  }
  // 数字键 1-9 快速跳页
  if(cur&&cur.id==='pg-search'&&/^[1-9]$/.test(e.key)&&e.ctrlKey){
   e.preventDefault();
   goPage(parseInt(e.key)-1);
  }
 }
});

function goBack(){
 const cur=document.querySelector('.page.active');
 if(cur&&cur.id==='pg-fav-inner'){go('fav');return;}
 if(cur&&(cur.id==='pg-fav'||cur.id==='pg-settings'||cur.id==='pg-stats')){go('search');return;}
 // 搜索页: 侧键/Esc = 翻回上一页(第0页时再按 = 关搜索面板)
 if(cur&&cur.id==='pg-search'&&currentPage>0){goPage(currentPage-1);return;}
 const searchP=document.getElementById('search-p');
 if(searchP&&searchP.classList.contains('open')){togSearch();}
}

async function doImport(){
 const b=document.getElementById('prog');
 const islandTxt=document.querySelector('.island-txt');
 b.classList.add('active');
 b.textContent='⏳ 正在连接…';
 if(islandTxt)islandTxt.innerHTML='<b>导入中…</b>';
 try{
  const r=await fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:'pixiv'})});
  const d=await r.json();
  if(d.ok && d.started){
   b.textContent='📥 导入中…';
   let secs=0;
   const poll=setInterval(async()=>{
    secs++;
    try{
     const sr=await fetch('/api/import-status');
     const sd=await sr.json();
     if(!sd.running){
      clearInterval(poll);
      b.classList.remove('active');
      if(sd.code===0){
       b.textContent='✅ 共 '+sd.count+' 幅';
       if(islandTxt)islandTxt.innerHTML='<b>PixivFavSearch</b> · '+sd.count+' 幅';
       setTimeout(()=>{b.style.width='0%';b.textContent=''},3000);
       await fetchWorks();renderWall();await fetchFavs();renderFavs();
       // 导入成功 → 自动启动缩略图全量预载(最新→最旧)
       try{
        await fetch('/api/thumb-prefetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
        const pb=document.getElementById('prefetch-btn');
        const pp=document.getElementById('prefetch-progress');
        if(pb)pb.textContent='停止预载';
        if(pp)pp.style.display='block';
        startPrefetchPolling();
       }catch(e){}
      }else{
       b.textContent='❌ '+(sd.msg||'失败');
       if(islandTxt)islandTxt.innerHTML='<b>PixivFavSearch</b>';
       setTimeout(()=>{b.style.width='0%';b.textContent=''},8000);
      }
     }else{
      if(islandTxt)islandTxt.innerHTML='<b>导入中…</b> '+secs+'秒';
     }
    }catch(e){clearInterval(poll);b.textContent='❌ 网络错误';}
   },1000);
  }else{
   b.classList.remove('active');
   b.textContent='❌ '+(d.error||'启动失败');
   setTimeout(()=>{b.style.width='0%';b.textContent=''},5000);
  }
 }catch(e){
  b.classList.remove('active');
  b.textContent='❌ 网络错误';
  setTimeout(()=>{b.style.width='0%';b.textContent=''},5000);
 }
}

function showTags(id){document.getElementById('tag-modal').classList.add('open');}
document.getElementById('tag-modal').addEventListener('click',function(e){if(e.target===this)this.classList.remove('open')});

function togSafe(){
 safe=!safe;
 document.getElementById('safe-tog').classList.toggle('on',safe);
 document.getElementById('safe-dot').classList.toggle('on',safe);
 currentPage=0;
 renderWall();
}

function newFolder(){
 const n=prompt('收藏夹名称：');
 if(n){folders.push({name:n,count:0,color:colorHash(n)});renderFavs();}
}

function togTheme(){document.getElementById('theme-panel').classList.toggle('open');}

function renderPresets(){
 const presets=[
  {n:'紫梦',a:'#c77dff',b:'#000'},{n:'深海',a:'#4a90d9',b:'#000814'},
  {n:'森林',a:'#27ae60',b:'#0a1a10'},{n:'樱粉',a:'#e91e63',b:'#1a0810'},
  {n:'暖橙',a:'#f39c12',b:'#1a1008'},{n:'烈焰',a:'#e74c3c',b:'#1a0808'},
  {n:'青色',a:'#1abc9c',b:'#081a18'},{n:'靛蓝',a:'#3f51b5',b:'#0a0e28'},
  {n:'玫瑰',a:'#ff6b6b',b:'#1a0a0a'},{n:'薄荷',a:'#10b981',b:'#061a14'},
  {n:'葡萄',a:'#8b5cf6',b:'#0e0820'},{n:'柠檬',a:'#eab308',b:'#1a1606'}
 ];
 document.getElementById('preset-themes').innerHTML=presets.map(t=>'<div class="color-swatch" style="background:'+t.a+'" onclick="applyTheme(\''+t.a+'\',\''+t.b+'\')" title="'+t.n+'"></div>').join('');
}

function applyTheme(a,b){
 document.documentElement.style.setProperty('--accent',a);
 document.documentElement.style.setProperty('--accent-g',a+'80');
 document.documentElement.style.setProperty('--bg',b);
 document.getElementById('pick-accent').value=a;
 document.getElementById('txt-accent').value=a;
 document.getElementById('pick-bg').value=b;
 document.getElementById('txt-bg').value=b;
 document.body.style.backgroundColor=b;
}

function applyAccent(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--accent',v);document.documentElement.style.setProperty('--accent-g',v+'80');document.getElementById('pick-accent').value=v;}}
function applyBg(v){if(/^#[0-9a-fA-F]{6}$/.test(v)){document.documentElement.style.setProperty('--bg',v);document.body.style.backgroundColor=v;document.getElementById('pick-bg').value=v;}}

function handleBg(input){
 if(input.files&&input.files[0]){
  const r=new FileReader();
  r.onload=function(e){
   const p=document.getElementById('bg-preview');
   p.classList.add('has-img');
   p.innerHTML='<img src="'+e.target.result+'"><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button>';
   document.body.style.backgroundImage='url('+e.target.result+')';
   document.body.style.backgroundSize='cover';
  };
  r.readAsDataURL(input.files[0]);
 }
}

function rmBg(){
 const p=document.getElementById('bg-preview');
 p.classList.remove('has-img');
 p.innerHTML='<span class="bg-txt">📷 点击导入图片</span><button class="bg-rm" onclick="event.stopPropagation();rmBg()">✕</button>';
 document.body.style.backgroundImage='';
}

function changeBounce(v){
 document.getElementById('bounce-val').textContent=v+'%';
 const y2=(1+v/100*0.8).toFixed(2);
 document.documentElement.style.setProperty('--ease-bounce','cubic-bezier(.22,'+y2+',.36,1)');
}

function toggleFx(el){
 el.classList.toggle('on');
 fxState[el.dataset.fx]=el.classList.contains('on');
 checkConflicts();
 updateSliders();
}

function updateSliders(){
 ['lightTrail','magnetic','tilt3d','ripple','breathing','particles','aurora','waves'].forEach(fx=>{
  const slider=document.getElementById(fx+'-slider');
  const val=document.getElementById(fx+'-val');
  if(slider&&val){
   slider.disabled=!fxState[fx];
   slider.parentElement.style.opacity=fxState[fx]?'1':'.4';
   val.textContent=slider.value+'%';
   slider.oninput=()=>{val.textContent=slider.value+'%';fxIntensity[fx]=parseInt(slider.value);};
  }
 });
}

function checkConflicts(){
 const warn=document.getElementById('conflict-warn');
 const txt=document.getElementById('conflict-text');
 for(const c of conflicts){
  if(c.effects.every(e=>fxState[e])){warn.classList.add('show');txt.textContent=c.msg;return;}
 }
 warn.classList.remove('show');
}

function resetAll(){
 applyTheme('#c77dff','#000');
 rmBg();
 document.getElementById('bounce-slider').value=100;
 changeBounce(100);
 document.querySelectorAll('.fx-tog').forEach(t=>{t.classList.add('on');fxState[t.dataset.fx]=true;});
 checkConflicts();
 updateSliders();
}

function saveAll(){
 // 真正保存: 主题色/背景/弹跳/全部效果开关+强度 → localStorage
 const cfg={
  accent:document.documentElement.style.getPropertyValue('--accent').trim()||'#c77dff',
  bg:document.documentElement.style.getPropertyValue('--bg').trim()||'#000',
  bgImg:(document.getElementById('bg-preview')&&document.getElementById('bg-preview').style.backgroundImage||'').slice(5,-2),
  bounce:document.getElementById('bounce-slider')?document.getElementById('bounce-slider').value:'100',
  fx:{},fxI:{}
 };
 for(const k in fxState)cfg.fx[k]=fxState[k];
 for(const k in fxIntensity)cfg.fxI[k]=fxIntensity[k];
 try{localStorage.setItem('pfs_theme',JSON.stringify(cfg));}catch(e){}
 const b=event.target;
 b.textContent='已保存 ✓';
 b.style.background='#27ae60';
 setTimeout(()=>{b.textContent='保存';b.style.background='';},1200);
 // 保存后自动关闭面板
 setTimeout(()=>{const p=document.getElementById('theme-panel');if(p)p.classList.remove('open');},900);
}

function loadTheme(){
 // 启动时恢复保存的主题设置
 let cfg=null;
 try{cfg=JSON.parse(localStorage.getItem('pfs_theme')||'null');}catch(e){}
 if(!cfg)return;
 if(cfg.accent){document.documentElement.style.setProperty('--accent',cfg.accent);document.documentElement.style.setProperty('--accent-g',cfg.accent+'80');const p=document.getElementById('pick-accent');if(p)p.value=cfg.accent;}
 if(cfg.bg){document.documentElement.style.setProperty('--bg',cfg.bg);const p=document.getElementById('pick-bg');if(p)p.value=cfg.bg;}
 if(cfg.bgImg&&cfg.bgImg!==''){document.body.style.backgroundImage=`url(${cfg.bgImg})`;document.body.classList.add('has-bg-img');}
 if(cfg.bounce&&document.getElementById('bounce-slider')){document.getElementById('bounce-slider').value=cfg.bounce;changeBounce(cfg.bounce);}
 if(cfg.fx){for(const k in cfg.fx){fxState[k]=cfg.fx[k];document.querySelectorAll(`.fx-tog[data-fx="${k}"]`).forEach(t=>t.classList.toggle('on',!!cfg.fx[k]));}}
 if(cfg.fxI){for(const k in cfg.fxI){fxIntensity[k]=cfg.fxI[k];const s=document.getElementById(k+'-slider');if(s)s.value=cfg.fxI[k];}}
 checkConflicts();
 updateSliders();
}

// 草稿设置系统
let draftSettings={};
async function loadDraft(){
 try{
  const r=await fetch('/api/settings/draft');
  draftSettings=await r.json();
  if(draftSettings.proxy)document.getElementById('set-proxy').value=draftSettings.proxy;
 }catch(e){console.log('loadDraft error',e)}
}
function onProxyChange(v){
 draftSettings.proxy=v;
 // 自动保存草稿
 fetch('/api/settings/draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draftSettings)});
 showDraftTip('草稿已保存');
}
let draftTipTimer;
function showDraftTip(text){
 const tip=document.getElementById('draft-tip');
 if(!tip)return;
 tip.textContent=text;
 tip.classList.add('show');
 clearTimeout(draftTipTimer);
 draftTipTimer=setTimeout(()=>tip.classList.remove('show'),2000);
}
async function applyDraft(){
 try{
  await fetch('/api/settings/draft/apply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draftSettings)});
  showDraftTip('设置已应用');
 }catch(e){showDraftTip('应用失败');}
}
async function cancelDraft(){
 try{
  await fetch('/api/settings/draft/cancel',{method:'POST'});
  loadDraft();
  showDraftTip('已取消');
 }catch(e){showDraftTip('取消失败');}
}

// ===== 缩略图全量预载 UI =====
let _pfTimer=null;
async function togglePrefetch(){
 const btn=document.getElementById('prefetch-btn');
 const prog=document.getElementById('prefetch-progress');
 // 若在跑 → 停止; 否则启动
 const st=await fetch('/api/thumb-prefetch/status').then(r=>r.json()).catch(()=>null);
 if(st&&st.running){
  await fetch('/api/thumb-prefetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stop:true})});
  if(btn)btn.textContent='已停止';
  return;
 }
 await fetch('/api/thumb-prefetch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({})});
 if(btn)btn.textContent='停止预载';
 if(prog)prog.style.display='block';
 startPrefetchPolling();
}
function startPrefetchPolling(){
 if(_pfTimer)clearInterval(_pfTimer);
 _pfTimer=setInterval(async()=>{
  try{
   const d=await fetch('/api/thumb-prefetch/status').then(r=>r.json());
   const btn=document.getElementById('prefetch-btn');
   const prog=document.getElementById('prefetch-progress');
   const stat=document.getElementById('prefetch-stat');
   const eta=document.getElementById('prefetch-eta');
   const bar=document.getElementById('prefetch-bar');
   const pct=d.total>0?Math.round(d.done/d.total*100):0;
   if(stat)stat.textContent=`✓ ${d.ok} 成功 · ${d.fail} 失败 · ${d.skip} 已有 · ${d.pending} 待下`;
   if(eta){
    if(d.running&&d.eta_s>=0)eta.textContent=`剩余 ~${Math.max(1,Math.round(d.eta_s/60))} 分钟 (${pct}%)`;
    else eta.textContent=d.running?'':'完成';
   }
   if(bar)bar.style.width=pct+'%';
   if(!d.running){
    clearInterval(_pfTimer);_pfTimer=null;
    if(btn)btn.textContent='开始预载';
    if(eta)eta.textContent=`完成! 本地缓存 ${d.cached} 张`;
    if(bar)bar.style.width='100%';
    // 完成后刷新当前页(新缩略图立即可见)
    renderWall();
   }
  }catch(e){}
 },1500);
}
// 启动时查一次: 上次没跑完的继续显示进度
setTimeout(async()=>{
 try{
  const d=await fetch('/api/thumb-prefetch/status').then(r=>r.json());
  if(d.running){
   const btn=document.getElementById('prefetch-btn');
   const prog=document.getElementById('prefetch-progress');
   if(btn)btn.textContent='停止预载';
   if(prog)prog.style.display='block';
   startPrefetchPolling();
  }
 }catch(e){}
},2000);

function loadTagFilters(){
 try{
  fetch('/api/tags').then(r=>r.json()).then(d=>{
   const bar=document.querySelector('.tag-bar-scroll');
   if(!bar)return;
   bar.innerHTML='<span class="tag-pill active" onclick="setTagFilter(\'\',this)">全部</span>';
   (d.tags||[]).slice(0,20).forEach(t=>{
    const span=document.createElement('span');
    span.className='tag-pill';
    span.textContent=t.tag+' ('+t.count+')';
    span.onclick=()=>setTagFilter(t.tag,span);
    bar.appendChild(span);
   });
  });
 }catch(e){console.log(e)}
}

function setTagFilter(tag,el){
 tagFilter=tag;
 statsFilter=null;   // 手动选标签时清掉统计筛选
 document.querySelectorAll('.tag-pill').forEach(p=>p.classList.remove('active'));
 if(el)el.classList.add('active');
 currentPage=0;
 renderWall();
}

function setColtagFilter(val){
 coltagFilter=val;
 statsFilter=null;   // 手动选收藏夹时清掉统计筛选
 currentPage=0;
 renderWall();
}

function setSortMode(val){
 sortMode=val;
 currentPage=0;
 renderWall();
}

function togOpenMode(el){
 const useBrowser=el.classList.toggle('on');
 setOpenMode(useBrowser?'browser':'inner');
}

function loadColtagOptions(){
 try{
  fetch('/api/coltags').then(r=>r.json()).then(d=>{
   const sel=document.getElementById('coltag-select');
   if(!sel)return;
   sel.innerHTML='<option value="">全部收藏夹</option>';
   (d.tags||d.data||[]).forEach(t=>{
    const opt=document.createElement('option');
    opt.value=t.tag;
    opt.textContent=t.tag+' ('+t.count+')';
    sel.appendChild(opt);
   });
  });
 }catch(e){console.log(e)}
}

function changeBgBrightness(v){
 document.getElementById('bg-br-val').textContent=v+'%';
 document.querySelector('.brightness-overlay').style.opacity=(100-v)/100;
}

document.addEventListener('mousemove',e=>{
 if(!fxState.lightTrail)return;
 const intensity=fxIntensity.lightTrail/100;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  const cx=r.left+r.width/2;const cy=r.top+r.height/2;
  const dx=e.clientX-cx;const dy=e.clientY-cy;const dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<200){card.style.boxShadow='0 '+(-dy*0.05)+'px '+(30-dist*0.1)+'px rgba(199,125,255,'+(0.3*(1-dist/200)*intensity)+')';}
  else{card.style.boxShadow='';}
 });
});

document.addEventListener('mousemove',e=>{
 if(!fxState.magnetic)return;
 const strength=fxIntensity.magnetic/100;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  const cx=r.left+r.width/2;const cy=r.top+r.height/2;
  const dx=e.clientX-cx;const dy=e.clientY-cy;const dist=Math.sqrt(dx*dx+dy*dy);
  if(dist<120){
   const force=(120-dist)/120*8*strength;
   card.querySelectorAll('.card-btn').forEach((btn,i)=>{
    const angle=(i-1)*0.3;
    btn.style.transform='translate('+Math.cos(angle)*force+'px,'+(Math.sin(angle)*force+force*0.5)+'px)';
   });
  }
 });
});

document.addEventListener('mousemove',e=>{
 if(!fxState.tilt3d)return;
 const maxAngle=fxIntensity.tilt3d/100*8;
 document.querySelectorAll('.card').forEach(card=>{
  const r=card.getBoundingClientRect();
  if(e.clientX>r.left&&e.clientX<r.right&&e.clientY>r.top&&e.clientY<r.bottom){
   const px=(e.clientX-r.left)/r.width-0.5;const py=(e.clientY-r.top)/r.height-0.5;
   card.style.transform='perspective(800px) rotateY('+(px*maxAngle)+'deg) rotateX('+(-py*maxAngle)+'deg) translateY(-8px) scale(1.03)';
  }
 });
});

document.addEventListener('click',e=>{
 if(!fxState.ripple)return;
 const ripple=document.createElement('div');
 ripple.style.cssText='position:fixed;left:'+(e.clientX-20)+'px;top:'+(e.clientY-20)+'px;width:40px;height:40px;border-radius:50%;background:radial-gradient(circle,rgba(199,125,255,.4),transparent);pointer-events:none;z-index:9999;animation:rippleExpand .6s ease-out forwards';
 document.body.appendChild(ripple);
 setTimeout(()=>ripple.remove(),600);
});

let lastMove=Date.now();
document.addEventListener('mousemove',()=>lastMove=Date.now());
function breathingLoop(){
 if(fxState.breathing&&Date.now()-lastMove>3000){
  const btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation='breathe 2s ease-in-out infinite';
 }else{
  const btn=document.querySelectorAll('.island-btn')[2];if(btn)btn.style.animation='';
 }
 requestAnimationFrame(breathingLoop);
}
// ===== 背景动态效果引擎 (粒子/极光/波浪/网格/星云/等高线) =====
// fxState.particles/aurora/waves/grid/nebula/contour 的真实渲染消费者
let _bgCanvas=null,_bgCtx=null,_bgParts=[],_bgWaves=[],_bgLast=0;
function _bgEnsureCanvas(){
 if(_bgCanvas)return true;
 try{
  _bgCanvas=document.createElement('canvas');
  _bgCanvas.style.cssText='position:fixed;inset:0;z-index:0;pointer-events:none';
  document.body.insertBefore(_bgCanvas,document.body.firstChild);
  _bgCtx=_bgCanvas.getContext('2d');
  _bgResize();
  window.addEventListener('resize',_bgResize);
  return true;
 }catch(e){return false}
}
function _bgResize(){
 if(!_bgCanvas)return;
 _bgCanvas.width=window.innerWidth||document.documentElement.clientWidth||1200;
 _bgCanvas.height=window.innerHeight||document.documentElement.clientHeight||800;
 // 重建粒子
 _bgParts=[];
 const n=Math.round((_bgCanvas.width*_bgCanvas.height)/26000);
 for(let i=0;i<n;i++)_bgParts.push({
  x:Math.random()*_bgCanvas.width,y:Math.random()*_bgCanvas.height,
  vx:(Math.random()-.5)*.4,vy:(Math.random()-.5)*.4,
  r:Math.random()*2+0.6,a:Math.random()*.5+.15
 });
 _bgWaves=[];
 for(let i=0;i<3;i++)_bgWaves.push({amp:18+i*10,len:.006+i*.003,spd:.012+i*.008,yOff:i*36});
}
function _hexA(hex,a){
 // #c77dff → rgba
 const h=hex.replace('#','');
 const r=parseInt(h.substr(0,2),16),g=parseInt(h.substr(2,2),16),b=parseInt(h.substr(4,2),16);
 return 'rgba('+r+','+g+','+b+','+a+')';
}
function _bgFrame(ts){
 requestAnimationFrame(_bgFrame);
 const anyOn=fxState.particles||fxState.aurora||fxState.waves||fxState.grid||fxState.nebula||fxState.contour;
 if(!anyOn||!_bgCanvas||!_bgCtx){if(_bgCtx)_bgCtx.clearRect(0,0,_bgCanvas.width,_bgCanvas.height);return}
 const W=_bgCanvas.width,H=_bgCanvas.height;
 const accent=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()||'#c77dff';
 const inten=k=>Math.max(.2,Math.min(1.6,(fxIntensity[k]||50)/50));
 _bgCtx.clearRect(0,0,W,H);
 _bgCtx.globalCompositeOperation='lighter';
 // 波浪层
 if(fxState.waves){
  const t=ts*.001*inten('waves');
  _bgWaves.forEach((wv,i)=>{
   _bgCtx.beginPath();
   _bgCtx.moveTo(0,H);
   for(let x=0;x<=W;x+=6){
    const y=H*.62+i*40+Math.sin(x*wv.len+t*wv.spd*60)*wv.amp*inten('waves');
    _bgCtx.lineTo(x,y);
   }
   _bgCtx.lineTo(W,H);
   _bgCtx.closePath();
   _bgCtx.fillStyle=_hexA(accent,.045-i*.012);
   _bgCtx.fill();
  });
 }
 // 极光流体
 if(fxState.aurora){
  const t=ts*.00035*inten('aurora');
  for(let i=0;i<3;i++){
   const gx=W*(.25+.25*i)+Math.sin(t+i*2)*W*.12;
   const gy=H*.28+Math.cos(t*1.3+i)*H*.1;
   const gr=Math.max(W,H)*.3;
   const g=_bgCtx.createRadialGradient(gx,gy,0,gx,gy,gr);
   g.addColorStop(0,_hexA(accent,.10*inten('aurora')));
   g.addColorStop(.5,_hexA(accent,.04*inten('aurora')));
   g.addColorStop(1,'rgba(0,0,0,0)');
   _bgCtx.fillStyle=g;
   _bgCtx.fillRect(0,0,W,H);
  }
 }
 // 粒子场
 if(fxState.particles){
  _bgCtx.fillStyle=_hexA(accent,1);
  const pi=inten('particles');
  _bgParts.forEach(p=>{
   p.x+=p.vx*pi;p.y+=p.vy*pi;
   if(p.x<-10)p.x=W+10;if(p.x>W+10)p.x=-10;
   if(p.y<-10)p.y=H+10;if(p.y>H+10)p.y=-10;
   _bgCtx.globalAlpha=p.a*pi;
   _bgCtx.beginPath();
   _bgCtx.arc(p.x,p.y,p.r,0,6.283);
   _bgCtx.fill();
  });
  _bgCtx.globalAlpha=1;
 }
 // 呼吸网格
 if(fxState.grid){
  const t=ts*.001;
  const step=52;
  _bgCtx.strokeStyle=_hexA(accent,.05+Math.sin(t)*.02);
  _bgCtx.lineWidth=1;
  for(let x=0;x<W;x+=step){_bgCtx.beginPath();_bgCtx.moveTo(x,0);_bgCtx.lineTo(x,H);_bgCtx.stroke()}
  for(let y=0;y<H;y+=step){_bgCtx.beginPath();_bgCtx.moveTo(0,y);_bgCtx.lineTo(W,y);_bgCtx.stroke()}
 }
 // 星云雾
 if(fxState.nebula){
  const t=ts*.0002;
  for(let i=0;i<4;i++){
   const nx=(Math.sin(t*.7+i*1.7)*.5+.5)*W;
   const ny=(Math.cos(t*.9+i*2.3)*.5+.5)*H;
   const nr=Math.max(W,H)*(.22+i*.06);
   const g=_bgCtx.createRadialGradient(nx,ny,0,nx,ny,nr);
   g.addColorStop(0,_hexA(accent,.07));
   g.addColorStop(1,'rgba(0,0,0,0)');
   _bgCtx.fillStyle=g;
   _bgCtx.fillRect(0,0,W,H);
  }
 }
 // 等高线
 if(fxState.contour){
  const t=ts*.0006;
  _bgCtx.strokeStyle=_hexA(accent,.08);
  _bgCtx.lineWidth=1.2;
  for(let i=0;i<8;i++){
   _bgCtx.beginPath();
   const cy=H*.5+Math.sin(t+i*.8)*H*.06;
   for(let x=0;x<=W;x+=8){
    const y=cy+Math.sin(x*.01+i)*30+Math.sin(x*.003+t*2)*20;
    x===0?_bgCtx.moveTo(x,y):_bgCtx.lineTo(x,y);
   }
   _bgCtx.stroke();
  }
 }
 _bgCtx.globalCompositeOperation='source-over';
}
if(_bgEnsureCanvas())requestAnimationFrame(_bgFrame);
breathingLoop();

renderWall();renderFavs();renderPresets();updateSliders();
loadTheme();
// 恢复链接打开方式开关显示
(function(){const t=document.getElementById('open-mode-tog');if(t)t.classList.toggle('on',getOpenMode()==='browser');})();
loadDraft();
loadTagFilters();loadColtagOptions();
changeBgBrightness(100);

</script>
<style>
@keyframes rippleExpand{from{transform:scale(0);opacity:1}to{transform:scale(3);opacity:0}}
@keyframes breathe{0%,100%{box-shadow:0 0 0 rgba(199,125,255,0)}50%{box-shadow:0 0 25px rgba(199,125,255,.5)}}

</style>"""

# --- 可复用的启动/停止函数(供 desktop_app 导入调用) ---
_server = None
# --- 外部窗口回调(desktop_app 启动时注册, 避免 exe 里循环 import) ---
_OPEN_EXTERNAL_WINDOW_CB = None

def register_open_window_callback(cb):
    """desktop_app 启动时调用, 把 open_external_window 注册进来。
    /api/open-work 通过回调开新 WebView 窗口, 不直接 import desktop_app
    (exe 里它是 __main__, import 会重新加载副本导致托盘死锁)。"""
    global _OPEN_EXTERNAL_WINDOW_CB
    _OPEN_EXTERNAL_WINDOW_CB = cb

_OPEN_BROWSER_CB = None

def register_browser_callback(cb):
    """desktop_app 启动时注册: 用系统默认浏览器打开链接(默认模式)。"""
    global _OPEN_BROWSER_CB
    _OPEN_BROWSER_CB = cb

def _auto_resume_prefetch():
    """启动 8s 后自动恢复缩略图预载(还有未完成的才跑)。
    WebView2 的 HTTP 缓存不持久化(WebView2Data 为空), 重启后浏览器缓存全丢;
    靠服务器磁盘缓存 + 自动补全, 保证翻页秒开不依赖浏览器缓存。"""
    def _delayed():
        time.sleep(8)
        try:
            pending = sum(
                1 for it in BOOKMARKS
                if not _thumb_cached(str(it.get("id", "")))
                and ("i.pximg.net" in (it.get("url") or "") or "s.pximg.net" in (it.get("url") or "")))
            if pending > 20:   # 剩太多才自动跑(零星几张留给按需下载)
                started = start_thumb_prefetch()
                print(f"[预载] 检测到 {pending} 张未缓存, 自动恢复预载: {started}")
            else:
                print(f"[预载] 仅剩 {pending} 张未缓存, 走按需下载")
        except Exception as e:
            print(f"[预载] 自动恢复异常: {e}")
    threading.Thread(target=_delayed, daemon=True).start()

def start_server(host="127.0.0.1", port=None, daemon=True):
    global _server
    if _server is not None and _server._serving_thread and _server._serving_thread.is_alive():
        return _server
    port = port or PORT
    # 提高连接排队容量: 默认 request_queue_size=5, 浏览器并发拉图/多设备访问时会拒连
    ThreadingHTTPServer.request_queue_size = 128
    # 线程上限: 防瞬时并发/慢速 DoS 耗尽线程
    import threading as _th
    _MAX_THREADS = 64   # 缩略图洪峰(200/页)+搜索并发, 32 会饿死 search
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
    # 自动恢复缩略图预载(桌面 exe import 启动 / 命令行直跑 都走这里)
    _auto_resume_prefetch()
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
    print(f"[OK] Started: http://127.0.0.1:{PORT}/ (whitelist={sorted(ALLOWED_IPS)})")
    try:
        while srv._serving_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()