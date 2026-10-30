"""配置加载、数值格式化与文本工具。

所有数字进入报告的路径只有两条：从来源原文抽取，或在 metrics 中由代码计算。
本模块只提供格式化，不做任何估算。
"""

from __future__ import annotations

import datetime as dt
import functools
import html
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "weekly.yaml"
SHANGHAI = ZoneInfo("Asia/Shanghai")
USER_AGENT = "ai-market-weekly/2.0 (+https://github.com/Cungenice/ai-market-weekly)"


@functools.lru_cache(maxsize=1)
def settings() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def cfg(path: str, default=None):
    """按 a.b.c 读取配置。"""
    node = settings()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def stock_pool() -> list[tuple[str, str, str]]:
    return [(str(code), str(name), str(theme)) for code, name, theme in cfg("stock_pool.a_share", [])]


def pool_by_code() -> dict[str, dict]:
    return {code: {"code": code, "name": name, "theme": theme} for code, name, theme in stock_pool()}


def filing_category(title: str) -> dict | None:
    for category in cfg("filings.categories", []):
        if any(term in title for term in category.get("match", [])):
            return category
    return None


def forbidden_phrases() -> list[str]:
    return list(cfg("compliance.forbidden_phrases", []))


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


# ---------------------------------------------------------------- 数值格式化


def yi(hkd: float) -> float:
    return hkd / 1e8


def fmt_turnover(hkd: float) -> str:
    """成交额按量级选择单位，保留两位有效小数，避免假精确。"""
    if hkd >= 1e12:
        return f"{hkd / 1e12:.2f} 万亿港元"
    if hkd >= 1e8:
        return f"{hkd / 1e8:.0f} 亿港元"
    return f"{hkd / 1e4:.0f} 万港元"


def fmt_pct(value: float, digits: int = 2, signed: bool = True) -> str:
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.{digits}f}%"


def fmt_points(value: float) -> str:
    return f"{value:+,.2f} 点"


def pct_phrase(value: float, digits: int = 2, flat: float = 0.05) -> str:
    """把涨跌幅写成短语，接近零时用「基本持平」，避免假精确。"""
    if abs(value) < flat:
        return "基本持平"
    return ("上涨 " if value > 0 else "下跌 ") + f"{abs(value):.{digits}f}%"


def fmt_index(value: float) -> str:
    return f"{value:,.2f}"


def fmt_int(value: float) -> str:
    return f"{value:,.0f}"


# ---------------------------------------------------------------- 数字识别

NUMBER_RE = re.compile(r"(?<![A-Za-z0-9.])\d[\d,]*(?:\.\d+)?")
CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def number_tokens(text: str) -> set[float]:
    """提取文本中的阿拉伯数字，统一为 float。"""
    found: set[float] = set()
    for raw in NUMBER_RE.findall(text or ""):
        cleaned = raw.replace(",", "").rstrip(".")
        try:
            found.add(float(cleaned))
        except ValueError:
            continue
    return found


def cn_number(text: str) -> float | None:
    """解析「三十亿元」「两点五」这类中文数字的常见形式。"""
    match = re.search(r"([零一二三四五六七八九十百千万亿两]+)(?:点([零一二三四五六七八九]+))?", text or "")
    if not match:
        return None
    whole, frac = match.group(1), match.group(2)
    units = {"十": 10, "百": 100, "千": 1000}
    total, current = 0, 0
    for char in whole:
        if char in CN_DIGITS:
            current = CN_DIGITS[char]
        elif char in units:
            total += (current or 1) * units[char]
            current = 0
        elif char == "万":
            total = (total + current) * 10_000
            current = 0
        elif char == "亿":
            total = (total + current) * 100_000_000
            current = 0
        else:
            return None
    value = float(total + current)
    if frac:
        value += float("0." + "".join(str(CN_DIGITS[c]) for c in frac if c in CN_DIGITS))
    return value


def title_similarity(left: str, right: str) -> float:
    def bigrams(value: str) -> set[str]:
        clean = re.sub(r"[\W_]+", "", value.lower(), flags=re.UNICODE)
        if len(clean) < 2:
            return {clean} if clean else set()
        return {clean[i:i + 2] for i in range(len(clean) - 1)}

    a, b = bigrams(left), bigrams(right)
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------- 期次


def issue_window(now: dt.datetime) -> dict:
    """期次锚定 ISO 周：区间为「上一个周一 09:30 → 现在」，即刚结束的这一周。

    这样周一 09:30 定时运行时区间恰好是完整的一周，周中补跑则覆盖到当前时刻，
    不会出现「统计区间包含未来日期」的情况；同一周内多次运行覆盖同一期次。
    """
    anchor_weekday = int(cfg("issue.anchor_weekday", 0))
    hour, minute = (int(part) for part in str(cfg("issue.anchor_time", "09:30")).split(":"))
    monday = now.date() - dt.timedelta(days=(now.weekday() - anchor_weekday) % 7)
    anchor = dt.datetime.combine(monday, dt.time(hour, minute), SHANGHAI)
    start = anchor - dt.timedelta(days=7) if now <= anchor else anchor
    end = now
    iso = start.date().isocalendar()
    return {
        "edition": f"{iso.year}-W{iso.week:02d}",
        "start": start,
        "end": end,
        "label": f"{start:%Y-%m-%d %H:%M} — {end:%Y-%m-%d %H:%M}",
        "week": iso.week,
        "iso_year": iso.year,
        "partial": end < start + dt.timedelta(days=7),
        "nominal_end": start + dt.timedelta(days=7),
    }


def parse_dt(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=SHANGHAI)
