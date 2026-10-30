"""确定性叙事：不依赖模型也能产出一份有判断的周报。

这里生成的是「模板化判断」——语句来自规则，数字来自 metrics 台账。
它与模型产出的报告使用同一套 schema 与同一套校验，因此可以互相替换。
"""

from __future__ import annotations

import datetime as dt

from . import settings as S


def market_phrase(metrics: dict) -> str:
    if not metrics.get("has_quote"):
        return ""
    change = metrics["week_change_pct"]
    drawdown = metrics["drawdown_from_high_pct"]
    turnover = metrics["turnover_change_pct"]
    if drawdown <= -0.8 and abs(change) < 0.5:
        return "恒指冲高回落，周线基本走平"
    if change >= 0.8:
        return "港股放量上行" if turnover > 5 else "港股小幅收涨"
    if change <= -0.8:
        return "港股周线收跌"
    return "港股窄幅震荡"


def filing_phrase(filings: list[dict]) -> str:
    if not filings:
        return ""
    themes = _theme_groups(filings)
    ranked = sorted(themes.items(), key=lambda item: len(item[1]), reverse=True)
    if ranked and len(ranked[0][1]) >= 2:
        theme, rows = ranked[0]
        categories = []
        for row in rows:
            for label in row.get("categories", []):
                if label not in categories:
                    categories.append(label)
        return f"{theme} {len(rows)} 家标的同日披露{'与'.join(categories[:3])}"
    if len(filings) >= 3:
        return f"{len(filings)} 家标的披露经营与资本动作"
    return f"{len(filings)} 家标的披露公告"


def build(metrics: dict, filings: list[dict], calendar_events: list[dict], period: dict,
          previous: dict | None = None) -> dict:
    headline = "，".join(part for part in (market_phrase(metrics), filing_phrase(filings)) if part)
    if not headline:
        headline = "本期无足够一手材料"

    highlights = _highlights(metrics, filings, calendar_events)
    used_in_highlights = {sid for story in highlights for sid in story.get("source_ids", [])}

    report: dict = {
        "headline": headline,
        "overview": _overview(metrics, filings, calendar_events),
        "overview_source_ids": _ids(metrics, filings),
        "ashare": _ashare(filings),
        "hk": _hk(metrics),
        "highlights": highlights,
        "other_updates": _other_updates(filings, exclude=used_in_highlights),
        "next_watch": _next_watch(calendar_events),
        "previous_check": _previous_check(previous),
        "origin": "rule",
    }
    return report


def _ids(metrics: dict, filings: list[dict]) -> list[str]:
    ids: list[str] = []
    if metrics.get("has_quote") and metrics.get("quote_ids"):
        ids.extend(metrics["quote_ids"][-1:])
    if filings:
        ids.append(filings[0]["id"])
    return list(dict.fromkeys(ids))


def _metric(key: str) -> str:
    return f"m:{key}"


def _overview(metrics: dict, filings: list[dict], calendar_events: list[dict]) -> str:
    parts: list[str] = []
    if metrics.get("has_quote"):
        parts.append(
            f"恒生指数本周收于 {S.fmt_index(metrics['close'])}，"
            f"较上周收盘{S.pct_phrase(metrics['week_change_pct'])}"
            f"（{S.fmt_points(metrics['week_change_points'])}）；"
            f"{metrics['high_date']} 触及周内高点 {S.fmt_index(metrics['high'])}，"
            f"之后 {metrics['sessions_after_high']} 个交易日有 {metrics['down_days_after_high']} 日收跌，"
            f"最新收市较该高点回落 {abs(metrics['drawdown_from_high_pct']):.2f}%。"
        )
        volume = ("量能明显收敛" if metrics["turnover_change_pct"] < -10
                  else "量能明显放大" if metrics["turnover_change_pct"] > 10 else "量能变化不大")
        direction = ("升至" if metrics["turnover_change_pct"] > 0.5
                     else "降至" if metrics["turnover_change_pct"] < -0.5 else "持平于")
        parts.append(
            f"主板成交额由 {metrics['first_session']} 的 {S.fmt_turnover(metrics['turnover_first'])}"
            f"{direction} {S.fmt_turnover(metrics['turnover_last'])}（{metrics['last_session']}），"
            f"较区间首日{S.pct_phrase(metrics['turnover_change_pct'])}，{volume}。"
        )
    else:
        parts.append("本期未取得交易所行情数据，市场表现部分留空。")

    if filings:
        themes = _theme_groups(filings)
        theme_text = "、".join(f"{theme} {len(rows)} 家" for theme, rows in
                               sorted(themes.items(), key=lambda item: len(item[1]), reverse=True)[:3])
        parts.append(f"A 股方向，本期标的池内 {len(filings)} 家发行人披露公告（{theme_text}），"
                     f"其中 {metrics.get('busiest_date', '')} 最为集中。")
    else:
        parts.append("A 股方向，本期标的池内无符合口径的公告。")

    deadline = next((row for row in calendar_events if "截止" in row["name"]), None)
    if deadline:
        parts.append(f"下周需留意 {deadline['date']} 的{deadline['name']}。")
    return "".join(parts)


def _ashare(filings: list[dict]) -> dict:
    if not filings:
        return {"summary": "本期标的池内未取得符合口径的上市公司公告。", "summary_source_ids": [],
                "drivers": []}
    themes = _theme_groups(filings)
    ranked = sorted(themes.items(), key=lambda item: len(item[1]), reverse=True)
    drivers = []
    for theme, rows in ranked[:3]:
        names = "、".join(row["issuer_name"] for row in rows[:3])
        drivers.append({
            "text": f"{theme}方向 {names} 等 {len(rows)} 家披露公告。",
            "source_ids": [row["id"] for row in rows[:3]],
            "metric_ids": [_metric("filings.issuers")],
        })
    return {
        "summary": f"本期 {len(filings)} 家发行人合计披露 {sum(row['filing_count'] for row in filings)} 份公告，"
                   f"集中在{'、'.join(label for label, _ in sorted(metrics_labels(filings).items(), key=lambda x: -x[1])[:2])}。",
        "summary_source_ids": [row["id"] for row in filings[:3]],
        "drivers": drivers,
    }


def metrics_labels(filings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in filings:
        for label in row.get("categories", []):
            counts[label] = counts.get(label, 0) + 1
    return counts


def _hk(metrics: dict) -> dict:
    if not metrics.get("has_quote"):
        return {"summary": "本期未取得港交所行情数据。", "summary_source_ids": [], "drivers": []}
    drivers = []
    for row in metrics.get("daily", []):
        drivers.append({
            "text": (f"{row['session_date']} 主板成交额 {S.fmt_turnover(row['turnover_hkd'])}，"
                     f"恒生指数收市 {S.fmt_index(row['index_close'])}。"),
            "source_ids": [sid for sid in [row.get("source_id")] if sid],
            "metric_ids": [_metric(f"hk.day.{row['session_date']}.turnover"),
                           _metric(f"hk.day.{row['session_date']}.close")],
        })
    return {
        "summary": (f"恒生指数本周{S.pct_phrase(metrics['week_change_pct'])}，"
                    f"振幅 {S.fmt_pct(metrics['amplitude_pct'], signed=False)}，"
                    f"日均成交额 {S.fmt_turnover(metrics['turnover_avg'])}。"),
        "summary_source_ids": metrics.get("quote_ids", [])[-2:],
        "drivers": drivers,
    }


def _highlights(metrics: dict, filings: list[dict], calendar_events: list[dict]) -> list[dict]:
    items: list[dict] = []

    if metrics.get("has_quote") and metrics["sessions"] >= 2:
        structure = []
        structure.append(f"{metrics['first_session']} 至 {metrics['last_session']} 共 {metrics['sessions']} 个交易日")
        structure.append(f"{metrics['high_date']} 收于周内高点 {S.fmt_index(metrics['high'])}")
        structure.append(f"其后 {metrics['sessions_after_high']} 个交易日有 {metrics['down_days_after_high']} 日收跌")
        structure.append(f"最新收市 {S.fmt_index(metrics['close'])} 较该高点回落 {abs(metrics['drawdown_from_high_pct']):.2f}%")
        if abs(metrics["week_change_pct"]) < 0.5:
            structure.append(f"但全周仅{S.pct_phrase(metrics['week_change_pct'])}，涨幅基本回吐")
        analysis = ("指数层面仍是区间震荡，日内高点未能转化为周线涨幅；"
                    "在成交额同步收缩的情况下，上行动能不足")
        if metrics["turnover_change_pct"] < -10:
            analysis += f"，{metrics['last_session']} 成交额较 {metrics['first_session']} 减少 {metrics['turnover_change_pct']:.1f}%"
        items.append({
            "market": "港股",
            "category": "市场结构",
            "title": f"恒指触及 {S.fmt_index(metrics['high'])} 后回落，周线{S.pct_phrase(metrics['week_change_pct'])}",
            "reported": "；".join(structure) + "。",
            "analysis": analysis + "。",
            "watch": f"关注下周成交额能否回到日均 {S.fmt_turnover(metrics['turnover_avg'])} 的水平。",
            "source_ids": metrics.get("quote_ids", [])[-2:],
            "metric_ids": [_metric("hk.week_change_pct"), _metric("hk.high"), _metric("hk.drawdown_from_high_pct"),
                           _metric("hk.turnover_change_pct")],
        })

    themes = _theme_groups(filings)
    for theme, rows in sorted(themes.items(), key=lambda item: len(item[1]), reverse=True):
        if len(rows) < 2:
            continue
        names = "、".join(f"{row['issuer_name']}（{row['issuer_code']}）" for row in rows[:3])
        labels = []
        for row in rows:
            for label in row.get("categories", []):
                if label not in labels:
                    labels.append(label)
        glosses = []
        for row in rows:
            for gloss in row.get("glosses", []):
                if gloss not in glosses:
                    glosses.append(gloss)
        items.append({
            "market": "A股",
            "category": "板块动向",
            "title": f"{theme} {len(rows)} 家标的同日披露{'与'.join(labels[:3])}",
            "reported": f"{metrics.get('busiest_date', '')}，{names} 集中披露{'、'.join(labels)}，"
                        f"合计 {sum(row['filing_count'] for row in rows)} 份公告。",
            "analysis": "；".join(glosses[:2]) + "。同一细分赛道集中披露，通常意味着该环节进入业绩验证期。",
            "watch": "关注披露后首个交易日的量价反应，以及同赛道未披露公司的后续公告。",
            "source_ids": [row["id"] for row in rows[:3]],
            "metric_ids": [_metric("filings.busiest_count")],
        })
        break

    if not items and filings:
        row = filings[0]
        items.append({
            "market": "A股", "category": "公司披露",
            "title": f"{row['issuer_name']}披露{'与'.join(row.get('categories', []))}",
            "reported": row["snippet"],
            "analysis": "；".join(row.get("glosses", [])[:2]) + "。",
            "watch": "关注公告披露后公司对业绩指引的进一步说明。",
            "source_ids": [row["id"]],
            "metric_ids": [_metric("filings.issuers")],
        })

    return items[: int(S.cfg("universe.max_highlights", 4))]


def _update_reported(row: dict) -> str:
    """正文只补标题没给的信息：具体披露了哪几份公告。"""
    announcements = row.get("announcements") or []
    if not announcements:
        return row.get("snippet", "")
    titles = [f"《{item['title'].removesuffix('的公告')}》" for item in announcements]
    shown = "、".join(titles[:2])
    more = f"等 {len(titles)} 份" if len(titles) > 2 else ""
    return f"本期披露{shown}{more}。"


def _category_meta() -> dict[str, dict]:
    return {item["label"]: item for item in S.cfg("filings.categories", [])}


def _update_note(row: dict, filings: list[dict]) -> str:
    """单条小结：这条公告在板块与周期中的位置，以及该类型的观察点。

    只使用采集到的字段（主题、类型、同批披露名单）与配置里的类型口径，
    不引入任何未见数据；因此不含数字，可安全绕开台账校验。
    """
    meta = _category_meta()
    theme = row.get("theme") or "其他"
    categories = row.get("categories") or []
    peers = [r for r in filings
             if r["id"] != row["id"] and (r.get("theme") or "其他") == theme]
    peer_names = [r["issuer_name"] for r in peers][:2]

    parts: list[str] = []
    if peer_names:
        parts.append(f"{theme}板块本期另有{'、'.join(peer_names)}披露公告，已进入成批披露阶段，可对照阅读")
    elif categories:
        parts.append(f"本期{theme}板块仅该标的披露{'、'.join(categories)}，暂无板块性共振，按个体事件处理")

    focus = [meta[c]["focus"] for c in categories if c in meta and meta[c].get("focus")]
    if focus:
        parts.append("；".join(focus[:2]))

    return "；".join(parts) + "。" if parts else ""


def _other_updates(filings: list[dict], exclude: set[str] | None = None) -> list[dict]:
    """「其他动态」只放重点没讲过的标的，避免同一条公告出现两次。"""
    exclude = exclude or set()
    pool = [row for row in filings if row["id"] not in exclude]
    rows = []
    for row in pool[: int(S.cfg("universe.max_other_updates", 6))]:
        categories = "、".join(row.get("categories", [])) or "公司公告"
        rows.append({
            "market": row["market"],
            "category": categories,
            "title": f"{row['issuer_name']}（{row['issuer_code']}）{categories}",
            "reported": _update_reported(row),
            "note": _update_note(row, pool),
            "source_ids": [row["id"]],
        })
    return rows


def _next_watch(calendar_events: list[dict]) -> list[dict]:
    rows = []
    for event in calendar_events[:6]:
        when = event["date"] if event["date"] == event["date_end"] else f"{event['date']}—{event['date_end']}"
        rows.append({
            "text": f"{when} {event['name']}",
            "date": event["date"],
            "date_end": event["date_end"],
            "when": when,
            "name": event["name"],
            "certainty": event["certainty"],
            "source_ids": [],
            "basis": f"日历规则：{event['rule_id']}",
        })
    return rows


def _previous_check(previous: dict | None) -> list[dict]:
    if not previous:
        return []
    prior = previous.get("report", {}).get("highlights") or []
    if not prior:
        label = previous.get("edition") or previous.get("date") or "上期"
        return [{
            "title": f"上期（{label}）未形成判断条目",
            "status": "待验证",
            "note": "该期只有数据与公告记录，没有可供复核的判断，本期不构成延续或推翻。",
            "source_ids": [],
        }]
    rows = []
    for story in (previous.get("report", {}).get("highlights") or [])[:3]:
        rows.append({
            "title": story.get("title", ""),
            "status": "待验证",
            "note": "上期判断，本期未取得足以判定的新证据。",
            "source_ids": [],
        })
    return rows


def _theme_groups(filings: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in filings:
        groups.setdefault(row.get("theme", "其他"), []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda row: row["published"])
    return groups


# 对外别名：编排层不直接调用下划线函数
calendar_watch = _next_watch
previous_check = _previous_check
