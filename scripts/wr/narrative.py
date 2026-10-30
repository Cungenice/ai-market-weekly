"""确定性叙事：不依赖模型也能产出一份有判断的周报。

这里生成的是「模板化判断」——语句来自规则，数字来自 metrics 台账。
它与模型产出的报告使用同一套 schema 与同一套校验，因此可以互相替换。
"""

from __future__ import annotations

import datetime as dt

from . import intel as intel_mod
from . import settings as S

_CN_DIGITS = "零一二三四五六七八九"


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
          previous: dict | None = None, intel_items: list[dict] | None = None) -> dict:
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
        "intel": _intel(intel_items or []),
        "other_updates": _other_updates(filings, exclude=used_in_highlights),
        "next_watch": _next_watch(calendar_events),
        "previous_check": _previous_check(previous),
        "origin": "rule",
    }
    return report


def _intel(intel_items: list[dict]) -> list[dict]:
    """无模型时的舆情条目：标签取采集阶段的规则初判，研判句取类型化的判断框架。"""
    required = set(S.cfg("intel.official_required_threads", []) or [])
    rows: list[dict] = []
    for item in intel_items:
        track = str(item.get("track") or "media")
        thread = str(item.get("thread") or "重要产业动态")
        title = str(item.get("title") or "").strip()
        rows.append({
            "thread": thread,
            "attribute": str(item.get("attribute") or "其他"),
            "track": track,
            "track_label": "官方" if track == "official" else "白名单媒体",
            "title": title,
            "note": intel_mod.rule_note({**item, "thread": thread}),
            "published": item["published"].isoformat(timespec="minutes"),
            "caveat": track == "media" and thread in required,
            "source_ids": [item["id"]],
        })
    return rows


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
        filings_count = sum(row["filing_count"] for row in rows)
        items.append({
            "market": "A股",
            "category": "板块动向",
            "title": f"{theme} {len(rows)} 家标的同期完成{'与'.join(labels[:3])}",
            "reported": f"{metrics.get('busiest_date', '')} 是本窗口披露最密集的一天，"
                        f"{theme}环节{_cn(len(rows))}家标的落在同一批，合计 {filings_count} 份公告，"
                        f"披露时点与口径一致。这意味着该环节的经营读数第一次能横向对照，"
                        f"而不再是各自独立的单点事件。",
            "analysis": "；".join(glosses[:2]) + "。同窗口密集披露不改变基本面，"
                        "但把定价依据从预期换成可核对的数据，板块内部分化因此显性化，"
                        "而不是整体同向移动。",
            "watch": "看这批披露后机构解读是否收敛到同一组指标，以及同环节未披露标的的跟进节奏。",
            "source_ids": [row["id"] for row in rows[:3]],
            "metric_ids": [_metric("filings.busiest_count")],
        })
        break

    if not items and filings:
        row = filings[0]
        labels = "、".join(row.get("categories", [])) or "公司公告"
        glosses = row.get("glosses", [])
        items.append({
            "market": "A股", "category": "公司披露",
            "title": f"{row['issuer_name']}披露{labels}",
            "reported": f"本期标的池内只有该标的披露{labels}，没有同批对照，"
                        f"这条只能按单点事件读，不宜外推为板块方向。",
            "analysis": ("；".join(glosses[:2]) + "。" if glosses
                         else "披露本身只提供个体信息，缺少同批对照时不足以形成板块结论。"),
            "watch": "关注公告披露后公司对业绩指引的进一步说明。",
            "source_ids": [row["id"]],
            "metric_ids": [_metric("filings.issuers")],
        })

    return items[: int(S.cfg("universe.max_highlights", 4))]


def _cn(count: int) -> str:
    """数量写成中文，避免与数字台账相互牵制（此处数量由代码统计，非模型估算）。"""
    if count == 2:
        return "两"
    if count < 10:
        return _CN_DIGITS[count]
    if count == 10:
        return "十"
    if count < 20:
        return "十" + _CN_DIGITS[count % 10]
    if count < 100:
        tens, ones = divmod(count, 10)
        return _CN_DIGITS[tens] + "十" + (_CN_DIGITS[ones] if ones else "")
    return str(count)


def _uniq(values: list[str]) -> list[str]:
    kept: list[str] = []
    for value in values:
        if value and value not in kept:
            kept.append(value)
    return kept


def _category_meta() -> dict[str, dict]:
    return {item["label"]: item for item in S.cfg("filings.categories", [])}


def _update_reading(row: dict, filings: list[dict]) -> str:
    """第一段写「这批披露透露了什么」，而不是「谁在哪天发了什么」。

    只使用采集到的结构字段（主题、公告类型、同批名单）与配置里的类型口径，
    不引入未见数据；披露家数由代码统计，因此可以安全外显。
    """
    meta = _category_meta()
    theme = row.get("theme") or "其他"
    categories = row.get("categories") or []
    peers = [r for r in filings
             if r["id"] != row["id"] and (r.get("theme") or "其他") == theme]

    if peers:
        lead = (f"{theme}环节本期{_cn(len(peers) + 1)}家标的落在同一披露窗口，"
                f"时点与口径一致，横向差异因此第一次可以被读出来")
    elif categories:
        lead = (f"{theme}环节本期只有该标的披露{'、'.join(categories)}，没有同批对照，"
                f"可读的只有它自己的口径变化")
    else:
        lead = f"{theme}环节本期只有该标的披露公告，缺少同批对照"

    glosses = _uniq([meta[c]["gloss"] for c in categories if c in meta and meta[c].get("gloss")])
    if glosses:
        lead += "。就公告类型看，这类信息" + "；".join(glosses[:2])
    return lead + "。"


_DISCLOSURE_CLOSERS = {
    "periodic": "报告期数据落地后，此前建立在预期上的定价需要重新校准",
    "forecast": "预告区间先于审计数据出现，方向比数值更值得记住",
    "buyback": "执行节奏比方案表述更能说明管理层的真实意愿",
    "order": "能见度提高之后，真正的检验转移到交付与回款",
    "capital": "股本一变，每股口径的比较基准就得换掉",
    "shareholder": "信号强度取决于后续是否还有同向动作",
    "regulatory": "问询是否被实质回应，决定这条信息是否已经用完",
}


def _update_note(row: dict, filings: list[dict]) -> str:
    """小结：把「透露了什么」收口成一句判断——该看什么，以及看错会怎样。"""
    meta = _category_meta()
    theme = row.get("theme") or "其他"
    categories = row.get("categories") or []
    peers = [r for r in filings
             if r["id"] != row["id"] and (r.get("theme") or "其他") == theme]
    focus = _uniq([meta[c]["focus"] for c in categories if c in meta and meta[c].get("focus")])
    closers = [v for k, v in _DISCLOSURE_CLOSERS.items()
               if k in {meta[c].get("id") for c in categories if c in meta}]

    parts: list[str] = []
    if focus:
        parts.append(focus[0])
    parts.append(f"同批还有{_cn(len(peers))}家可比，单家强弱不足以推出板块结论" if peers
                 else "同环节没有对照，这一条只能当个体样本，等下一家披露后再定方向")
    if closers:
        parts.append(closers[0])
    return "；".join(parts) + "。"


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
            # 标题只当标签用，不写成「X 披露 Y」的公告句式——信息在下两段
            "title": f"{row['issuer_name']}（{row['issuer_code']}） · {categories}",
            "reported": _update_reading(row, pool),
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
