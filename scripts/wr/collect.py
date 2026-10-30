"""四通道采集：公告 / 行情 / 日历 / 线索。

设计原则：
- 每个通道独立失败，任一通道失败不阻断其余通道。
- 区分「没有数据」与「抓取失败」：失败必须留下日志与频道级状态。
- 线索通道只做触发，产出仍须落在一手域名上才可进入正文。
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from . import settings as S

OFFICIAL_DOMAINS = ("gov.cn", "csrc.gov.cn", "sse.com.cn", "szse.cn", "hkex.com.hk", "hkexnews.hk", "cninfo.com.cn")
MEDIA_DOMAINS = ("reuters.com", "bloomberg.com", "ft.com", "wsj.com", "caixin.com", "yicai.com", "cls.cn",
                 "21jingji.com", "cnstock.com", "stcn.com", "thepaper.cn", "eastmoney.com", "sina.com.cn")
TOPIC_TERMS = ("人工智能", "AI", "半导体", "芯片", "算力", "机器人", "科技创新", "大模型", "云计算", "软件")
EVENT_TERMS = ("公告", "披露", "业绩", "财报", "订单", "合同", "融资", "上市", "政策", "指数", "监管", "发布", "收购")
OPINION_TERMS = ("传闻", "预测", "或将", "有望", "押注", "观点", "策略")
MARKET_SIGNAL_TERMS = ("指数", "成交额", "成交量", "换手率", "资金流", "南向资金", "北向资金", "港股通",
                       "融资融券", "回购", "增持", "减持", "解禁", "股价", "收盘", "涨幅", "跌幅", "波动", "估值")
MARKET_TERMS = ("A股", "港股", "上市公司", "股票", "股价", "股市", "指数", "ETF", "资金", "成交", "涨", "跌",
                "市值", "营收", "净利润", "业绩", "财报", "三季报", "订单", "合同", "融资", "IPO", "招股",
                "港交所", "交易所", "公告", "监管", "产业政策", "基金", "投资者", "资本市场")
CONTEXT_TERMS = ("科创50", "科创板", "恒生科技", "恒科指", "港股科技", "科技股", "科网股", "南向资金",
                 "港股通互联网", "科技板块", "科技赛道", "人工智能指数", "半导体指数", "产业政策")
DISCOVERY_FEEDS = [
    ("A股", "A股 人工智能 半导体 算力 机器人 科创板 公告 site:sse.com.cn"),
    ("A股", "A股 AI 半导体 芯片 业绩 公告 site:szse.cn"),
    ("港股", "港股 人工智能 半导体 科技公司 公告 业绩 site:hkexnews.hk"),
    ("港股", "港股 AI 半导体 科技指数 市场数据 site:hkex.com.hk"),
]


# ---------------------------------------------------------------- 通用


def _tier_for(host: str) -> tuple[str, str]:
    host = (host or "").lower().removeprefix("www.")
    if any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS):
        return "official", "交易所/监管/公司官网"
    if any(host == d or host.endswith("." + d) for d in MEDIA_DOMAINS):
        return "media", "财经媒体"
    return "unrated", "未分级来源"


def is_official_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return parsed.scheme == "https" and any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _looks_date_only(stamp: dt.datetime) -> bool:
    return (stamp.hour, stamp.minute) in {(0, 0), (23, 59)}


def _audit(payload: bytes, prefix: str) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    try:
        audit_dir = Path(os.environ.get("RUNNER_TEMP", str(Path("/tmp")))) / "market-weekly-audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        (audit_dir / f"{prefix}-{digest[:16]}.bin").write_bytes(payload)
    except OSError:
        pass
    return digest


# ---------------------------------------------------------------- 公告通道


def _cninfo_post(path: str, fields: dict) -> object:
    """巨潮接口会限流（504/QPS 拒绝），重试并退避，仍失败则抛给上层降级。"""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(
        "https://www.cninfo.com.cn" + path, data=body, method="POST",
        headers={"User-Agent": S.USER_AGENT, "Content-Type": "application/x-www-form-urlencoded",
                 "Referer": "https://www.cninfo.com.cn/new/disclosure"},
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
            if not payload.strip():
                raise ValueError("Empty HTTP response")
            print(json.dumps({"stage": "fetch_cninfo", "url": request.full_url,
                              "fetched_at": dt.datetime.now(S.SHANGHAI).isoformat(),
                              "http_status": 200, "sha256": _audit(payload, "cninfo")}, ensure_ascii=False))
            return json.loads(payload.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            if attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    raise last_error if last_error else RuntimeError("cninfo request failed")


def _org_id(code: str) -> str | None:
    matches = _cninfo_post("/new/information/topSearch/query", {"keyWord": code, "maxNum": 10})
    if not isinstance(matches, list):
        raise ValueError("topSearch schema changed")
    match = next((row for row in matches if str(row.get("code", "")) == code), None)
    if match is None:
        return None
    org = match.get("orgId")
    return org if isinstance(org, str) and org else None


def _fetch_one_issuer(entry: tuple[str, str, str], start: dt.datetime, end: dt.datetime) -> list[dict]:
    code, name, theme = entry
    time.sleep(0.12)
    org = _org_id(code)
    if not org:
        print(f"CNINFO {code} {name}: orgId not found")
        return []
    column = "sse" if code.startswith(("6", "9")) else "szse"
    result = _cninfo_post("/new/hisAnnouncement/query", {
        "stock": f"{code},{org}", "tabName": "fulltext", "pageSize": 30,
        "pageNum": 1, "column": column, "seDate": f"{start:%Y-%m-%d}~{end:%Y-%m-%d}",
        "isHLtitle": "true",
    })
    if not isinstance(result, dict):
        raise ValueError("announcement schema changed")
    rows = result.get("announcements") or []
    include = tuple(S.cfg("filings.include_title_terms", []))
    exclude = tuple(S.cfg("filings.exclude_title_terms", []))
    kept = []
    for row in rows:
        title = re.sub(r"<[^>]+>", "", html.unescape(str(row.get("announcementTitle", "")))).strip()
        stamp, adjunct = row.get("announcementTime"), row.get("adjunctUrl")
        if not title or not isinstance(stamp, (int, float)) or not isinstance(adjunct, str):
            continue
        published = dt.datetime.fromtimestamp(stamp / 1000, S.SHANGHAI)
        if not start <= published <= end:
            continue
        if include and not any(term in title for term in include):
            continue
        if any(term in title for term in exclude):
            continue
        category = S.filing_category(title)
        if category is None:
            continue
        kept.append({
            "title": title,
            "url": urllib.parse.urljoin("https://static.cninfo.com.cn/", adjunct.lstrip("/")),
            "published": published,
            "category_id": category["id"],
            "category_label": category["label"],
            "gloss": category["gloss"],
        })
    print(f"CNINFO {code} {name} [{theme}]: {len(rows)} returned, {len(kept)} eligible")
    return _merge_issuer(code, name, theme, kept)


def _merge_issuer(code: str, name: str, theme: str, rows: list[dict]) -> list[dict]:
    """同一发行人同一期内的多条公告合并为一条，避免标题刷屏。"""
    if not rows:
        return []
    order = [c["id"] for c in S.cfg("filings.categories", [])]
    rows.sort(key=lambda r: (order.index(r["category_id"]) if r["category_id"] in order else 99, r["published"]))
    categories = list(dict.fromkeys(row["category_label"] for row in rows))
    first = rows[0]
    latest = max(row["published"] for row in rows)
    link_titles = "、".join(dict.fromkeys(row["title"].removesuffix("的公告") for row in rows))
    return [{
        "channel": "company_fact",
        "market": "A股",
        "title": f"{name}（{code}）{'/'.join(categories)}",
        "url": first["url"],
        "published": latest,
        "date_only": _looks_date_only(latest),
        "source": "巨潮资讯网",
        "source_url": "https://www.cninfo.com.cn",
        "source_tier": "official",
        "source_tier_label": "上市公司一手公告",
        "registered_source_id": "cninfo",
        "snippet": f"{name}（{code}）本期披露：{link_titles}。",
        "issuer_code": code,
        "issuer_name": name,
        "theme": theme,
        "categories": categories,
        "glosses": list(dict.fromkeys(row["gloss"] for row in rows)),
        "filing_count": len(rows),
        "announcements": [
            {"title": row["title"], "url": row["url"],
             "date": row["published"].strftime("%Y-%m-%d"),
             "category": row["category_label"],
             "date_only": _looks_date_only(row["published"])}
            for row in rows
        ],
    }]


def collect_filings(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], dict]:
    pool = S.stock_pool()
    items: list[dict] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool_exec:
        futures = {pool_exec.submit(_fetch_one_issuer, entry, start, end): entry for entry in pool}
        for future in concurrent.futures.as_completed(futures):
            code, name, _ = futures[future]
            try:
                items.extend(future.result())
            except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                failures.append(f"{code}:{type(exc).__name__}")
                print(f"CNINFO {code} {name} unavailable: {exc}")
    items.sort(key=lambda row: row["published"], reverse=True)
    return items, {"channel": "company_fact", "ok": bool(items) or not failures,
                   "count": len(items), "failures": failures, "pool": len(pool)}


# ---------------------------------------------------------------- 行情通道


def collect_quotes(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    looked = 0
    day = start.date()
    while day <= end.date():
        if day.weekday() < 5:
            looked += 1
            url = f"https://www.hkex.com.hk/eng/stat/smstat/dayquot/d{day:%y%m%d}e.htm"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": S.USER_AGENT})
                with urllib.request.urlopen(request, timeout=20) as response:
                    payload = response.read()
                page = html.unescape(re.sub(r"<[^>]+>", " ", payload.decode("utf-8", errors="replace")))
                page = re.sub(r"\s+", " ", page)
                date_label = day.strftime("%d %b %Y").lstrip("0").upper()
                if date_label not in page.upper() or "MARKET HIGHLIGHTS" not in page:
                    print(f"HKEX quote rejected {url}: date or section mismatch")
                    day += dt.timedelta(days=1)
                    continue
                turnover = re.search(r"Today's Turnover:\s*\(HK\$\):\s*([0-9,]+)", page, re.I)
                index = re.search(r"HANG SENG INDEX\s+([0-9,.]+)\s+([0-9,.]+)\s+([0-9,.]+)", page, re.I)
                if not turnover or not index:
                    print(f"HKEX quote rejected {url}: required figures absent")
                    day += dt.timedelta(days=1)
                    continue
                stamp = dt.datetime.combine(day, dt.time(16, 0), S.SHANGHAI)
                rows.append({
                    "channel": "quote", "market": "港股",
                    "title": f"港交所 {day.isoformat()} 每日成交及恒生指数",
                    "url": url, "published": stamp, "date_only": True,
                    "session_date": day.isoformat(),
                    "source": "香港交易所", "source_url": "https://www.hkex.com.hk",
                    "source_tier": "official", "source_tier_label": "港交所官方行情",
                    "registered_source_id": "hkex",
                    "snippet": (f"日期 {day.isoformat()}。主板成交额 {turnover.group(1)} 港元。"
                                f"恒生指数收市 {index.group(2)}，前收市 {index.group(3)}。"),
                    "turnover_hkd": float(turnover.group(1).replace(",", "")),
                    "index_close": float(index.group(2).replace(",", "")),
                    "index_prev": float(index.group(3).replace(",", "")),
                })
            except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
                print(f"HKEX quote unavailable {url}: {exc}")
        day += dt.timedelta(days=1)
    rows.sort(key=lambda row: row["published"])
    return rows, {"channel": "quote", "ok": bool(rows), "count": len(rows), "sessions_looked": looked}


# ---------------------------------------------------------------- 线索通道


def _fetch_feed(market: str, query: str, start: dt.datetime, end: dt.datetime) -> list[dict]:
    params = urllib.parse.urlencode({"q": f"{query} when:7d", "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
    url = f"https://news.google.com/rss/search?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": S.USER_AGENT})
    payload = b""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
            if not payload.strip():
                raise ValueError("Empty HTTP response")
            root = ET.fromstring(payload)
            if root.tag != "rss" or root.find("channel") is None:
                raise ValueError("Unexpected RSS schema")
            break
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    entries: list[dict] = []
    for node in root.findall("./channel/item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        published_raw = (node.findtext("pubDate") or "").strip()
        description = re.sub(r"<[^>]+>", " ", node.findtext("description") or "")
        description = html.unescape(re.sub(r"\s+", " ", description)).strip()
        source_node = node.find("source")
        source = (source_node.text or "").strip() if source_node is not None else "来源未标注"
        source_url = source_node.get("url", "").strip() if source_node is not None else ""
        if not title or not link or not published_raw:
            continue
        try:
            published = email.utils.parsedate_to_datetime(published_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        published = published.astimezone(S.SHANGHAI)
        if not start <= published <= end:
            continue
        tier, tier_label = _tier_for(urllib.parse.urlsplit(source_url).hostname or "")
        entries.append({
            "channel": "clue", "market": market, "title": title, "url": link,
            "published": published, "date_only": False, "source": source, "source_url": source_url,
            "source_tier": tier, "source_tier_label": tier_label, "snippet": description[:800],
        })
    return entries


def _resolve_google(url: str) -> tuple[str, str]:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() != "news.google.com":
        return url, ""
    article_id = parsed.path.rstrip("/").split("/")[-1]
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Cookie": "CONSENT=PENDING+987",
    }
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    try:
        page_request = urllib.request.Request(f"https://news.google.com/rss/articles/{article_id}", headers=headers)
        with opener.open(page_request, timeout=20) as response:
            page = response.read().decode("utf-8", errors="replace")
        signature = re.search(r'data-n-a-sg="([^"]+)"', page)
        timestamp = re.search(r'data-n-a-ts="(\d+)"', page)
        if not signature or not timestamp:
            return url, "Google article page lacks resolver signature"
        locale = ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1]
        inner = json.dumps(["garturlreq", [locale, "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                            article_id, int(timestamp.group(1)), signature.group(1)],
                           ensure_ascii=False, separators=(",", ":"))
        outer = json.dumps([[["Fbv4je", inner]]], ensure_ascii=False, separators=(",", ":"))
        post_request = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=urllib.parse.urlencode({"f.req": outer}).encode("utf-8"),
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                     "Origin": "https://news.google.com",
                     "Referer": f"https://news.google.com/rss/articles/{article_id}",
                     "X-Same-Domain": "1"},
            method="POST")
        with opener.open(post_request, timeout=20) as response:
            payload = response.read().decode("utf-8", errors="replace")
        marker = payload.find("\n\n")
        if marker < 0:
            return url, "Google resolver response has an unexpected format"
        frames = json.loads(payload[marker + 2:])
        frame = next((row for row in frames if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr"), None)
        if not frame or not frame[2]:
            return url, "Google resolver returned no publisher URL"
        resolved = json.loads(frame[2])[1]
        if is_official_url(resolved):
            return resolved, ""
        return url, "Resolved publisher is not an allowed first-party domain"
    except (urllib.error.URLError, TimeoutError, ValueError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return url, f"resolve failed: {type(exc).__name__}"


def _is_relevant(item: dict) -> bool:
    text = f"{item['title']} {item['snippet']}".lower()
    has_topic = any(term.lower() in text for term in TOPIC_TERMS + CONTEXT_TERMS)
    has_market = any(term.lower() in text for term in MARKET_TERMS)
    fund_product = any(term in text for term in ("ETF", "基金", "QDII", "交易型开放式指数证券投资基金"))
    periodic = bool(re.search(r"(第\s*[123四三二一]\s*季度报告|[三二一]季报|季度报告)", text))
    if fund_product and periodic:
        return any(term in text for term in ("净申购", "净赎回", "份额变动", "持仓变动"))
    return has_topic and has_market


def collect_clues(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], dict]:
    by_url: dict[str, dict] = {}
    failures: list[str] = []
    for market, query in DISCOVERY_FEEDS:
        try:
            found = _fetch_feed(market, query, start, end)
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError) as exc:
            failures.append(f"{market}:{type(exc).__name__}")
            print(f"clue feed failed ({market}): {exc}")
            continue
        for item in found:
            key = item["url"].split("&ved=")[0]
            existing = by_url.get(key)
            if existing is None:
                by_url[key] = item
            elif item["source_tier"] == "official" and existing["source_tier"] != "official":
                existing.update({k: item[k] for k in ("source", "source_url", "source_tier", "source_tier_label")})
    primary = [item for item in by_url.values() if item["source_tier"] == "official"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        resolved = list(executor.map(lambda item: _resolve_google(item["url"])[0], primary))
    kept: list[dict] = []
    for item, url in zip(primary, resolved):
        if not is_official_url(url):
            continue
        item["url"] = url
        item["source_tier_label"] = "交易所/监管/公司官网"
        if _is_relevant(item):
            kept.append(item)
    print(f"clue channel: {len(by_url)} raw, {len(primary)} official, {len(kept)} relevant")
    return kept, {"channel": "clue", "ok": bool(kept) or not failures, "count": len(kept), "failures": failures}


# ---------------------------------------------------------------- 日历通道


def _next_month_window(now: dt.datetime, window: tuple[int, int]) -> tuple[dt.date, dt.date] | None:
    low, high = window
    for offset in (0, 1):
        year = now.year + (now.month - 1 + offset) // 12
        month = (now.month - 1 + offset) % 12 + 1
        try:
            start = dt.date(year, month, low)
        except ValueError:
            continue
        if start >= now.date():
            day = min(high, 28)
            return start, dt.date(year, month, day)
    return None


def collect_calendar(now: dt.datetime, horizon_days: int = 12) -> tuple[list[dict], dict]:
    """下周日历：规则推算为主，登记事项为辅。不依赖任何外部接口。"""
    events: list[dict] = []
    limit = now.date() + dt.timedelta(days=horizon_days)
    for rule in S.cfg("calendar.recurring", []):
        window = tuple(rule.get("window", [1, 1]))
        upcoming = _next_month_window(now, window)
        if not upcoming:
            continue
        start, end = upcoming
        if start > limit:
            continue
        events.append({
            "date": start.isoformat(),
            "date_end": end.isoformat(),
            "name": rule["name"],
            "note": rule.get("note", ""),
            "rule_id": rule["id"],
            "certainty": "规则推算",
        })
    for fixed in S.cfg("calendar.deadlines", []):
        for year in (now.year, now.year + 1):
            try:
                when = dt.date(year, int(fixed["month"]), int(fixed["day"]))
            except ValueError:
                continue
            if now.date() <= when <= limit:
                events.append({
                    "date": when.isoformat(), "date_end": when.isoformat(), "name": fixed["name"],
                    "note": fixed.get("note", ""), "rule_id": fixed["id"], "certainty": "法定截止日",
                })
    for known in S.cfg("calendar.known_events", []) or []:
        try:
            when = dt.date.fromisoformat(str(known["date"]))
        except (KeyError, ValueError):
            continue
        if now.date() <= when <= limit:
            events.append({"date": when.isoformat(), "date_end": when.isoformat(), "name": known["name"],
                           "note": known.get("note", ""), "rule_id": "known", "certainty": "已登记"})
    events.sort(key=lambda row: row["date"])
    return events, {"channel": "calendar", "ok": bool(events), "count": len(events)}
