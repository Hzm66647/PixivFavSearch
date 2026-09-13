"""PixivFavSearch - 本地书签搜索工具
启动后浏览器打开 http://127.0.0.1:8897/
输入标题关键词 -> 列出匹配作品(标题/作者/链接/缩略图)
缩略图按需下载并缓存到 data/thumbs/
"""
VERSION = "1.1.0"
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
            reload_pixiv_if_changed()  # pixiv 数据热重载(增量更新后免重启)
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
            for it in BOOKMARKS:
                # 限定收藏标签(coltag):作品必须属于该收藏标签
                if coltag_ids is not None and str(it.get("id")) not in coltag_ids:
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
        elif u.path == "/api/settings":
            # 返回当前配置(proxy 等)
            cfg = load_config()
            self.send_json(200, {"proxy": cfg.get("proxy", "http://127.0.0.1:10808")})
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
                import json
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
        m_works = _re.match(r"^/api/coltags/([^/]+)/works$", u.path)
        if m_works and self.command == "GET":
            name = urllib.parse.unquote(m_works.group(1))
            if name not in COLTAG_MAP:
                return self.send_json(404, {"error": "标签不存在"})
            ids = COLTAG_MAP[name]
            items = [_pub(it, []) for it in BOOKMARKS if str(it.get("id")) in ids]
            return self.send_json(200, {"total": len(items), "tag": name, "items": items})

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

</style>
</head>
<body>
<!-- 灵动岛 -->
<div class="island" id="island">
  <button class="island-btn" onclick="document.getElementById('q').focus()" title="搜索 (/)">🔍</button>
  <span class="island-txt"><b>PixivFavSearch</b> · <span id="island-count">0</span> 幅</span>
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
<div class="search-float" id="search-p"><span class="search-icon">🔍</span><input placeholder="搜索..." onkeydown="if(event.key==='Enter')doSearch(this.value)"></div>

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

INDEX = r"""<!doctype html><html lang=zh><meta charset=utf-8><title>PixivFavSearch</title>
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
    print(f"[OK] Started: http://127.0.0.1:{PORT}/ (whitelist={sorted(ALLOWED_IPS)})")
    try:
        while srv._serving_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server()