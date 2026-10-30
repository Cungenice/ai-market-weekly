"""派生指标：所有计算只发生在这里。

模型不允许生成数字，但也不应该被禁止**计算**——涨跌幅、振幅、环比都是确定性运算，
由代码算出后进入台账（ledger），供正文引用并接受校验。
"""

from __future__ import annotations

import datetime as dt

from . import settings as S


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100 if old else 0.0


def build_metrics(quotes: list[dict], filings: list[dict]) -> dict:
    sessions = sorted(quotes, key=lambda row: row["session_date"])
    metrics: dict = {"has_quote": bool(sessions), "ledger": [], "series": {}, "notes": []}

    if sessions:
        first, last = sessions[0], sessions[-1]
        base = first["index_prev"]
        closes = [row["index_close"] for row in sessions]
        turnovers = [row["turnover_hkd"] for row in sessions]
        high_row = max(sessions, key=lambda row: row["index_close"])
        low_row = min(sessions, key=lambda row: row["index_close"])
        changes = [_pct(row["index_close"], row["index_prev"]) for row in sessions]
        after_high = sessions[sessions.index(high_row) + 1:]
        down_after_high = sum(1 for row in after_high if row["index_close"] < row["index_prev"])

        metrics.update({
            "sessions": len(sessions),
            "base_prev": base,
            "close": last["index_close"],
            "prev_close": last["index_prev"],
            "week_change_pct": _pct(last["index_close"], base),
            "week_change_points": last["index_close"] - base,
            "high": high_row["index_close"],
            "high_date": high_row["session_date"],
            "low": low_row["index_close"],
            "low_date": low_row["session_date"],
            "amplitude_pct": (high_row["index_close"] - low_row["index_close"]) / base * 100,
            "drawdown_from_high_pct": _pct(last["index_close"], high_row["index_close"]),
            "down_days_after_high": down_after_high,
            "sessions_after_high": len(after_high),
            "up_days": sum(1 for value in changes if value > 0),
            "down_days": sum(1 for value in changes if value < 0),
            "turnover_first": first["turnover_hkd"],
            "turnover_last": last["turnover_hkd"],
            "turnover_avg": sum(turnovers) / len(turnovers),
            "turnover_change_pct": _pct(last["turnover_hkd"], first["turnover_hkd"]),
            "turnover_last_vs_avg_pct": _pct(last["turnover_hkd"], sum(turnovers) / len(turnovers)),
            "turnover_max": max(turnovers),
            "turnover_min": min(turnovers),
            "turnover_max_min_ratio": max(turnovers) / min(turnovers) if min(turnovers) else 0.0,
            "first_session": first["session_date"],
            "last_session": last["session_date"],
            "data_through": last["session_date"],
            "series": {
                "dates": [row["session_date"] for row in sessions],
                "index": closes,
                "turnover": turnovers,
                "change_pct": changes,
            },
        })
        ledger = [
            ("hk.week_change_pct", metrics["week_change_pct"], "恒指周涨跌幅"),
            ("hk.week_change_points", metrics["week_change_points"], "恒指周涨跌点数"),
            ("hk.close", metrics["close"], "恒指最新收市"),
            ("hk.high", metrics["high"], "恒指周内最高收市"),
            ("hk.low", metrics["low"], "恒指周内最低收市"),
            ("hk.amplitude_pct", metrics["amplitude_pct"], "恒指周内振幅"),
            ("hk.drawdown_from_high_pct", metrics["drawdown_from_high_pct"], "自周内高点的回落幅度"),
            ("hk.turnover_first", first["turnover_hkd"], "区间首个交易日主板成交额"),
            ("hk.turnover_last", last["turnover_hkd"], "区间最后一个交易日主板成交额"),
            ("hk.turnover_avg", metrics["turnover_avg"], "区间日均主板成交额"),
            ("hk.turnover_change_pct", metrics["turnover_change_pct"], "成交额较区间首日变化"),
            ("hk.turnover_last_vs_avg_pct", metrics["turnover_last_vs_avg_pct"], "最后一日成交额较日均变化"),
            ("hk.turnover_max", metrics["turnover_max"], "区间最高单日成交额"),
            ("hk.turnover_min", metrics["turnover_min"], "区间最低单日成交额"),
            ("hk.down_days_after_high", float(metrics["down_days_after_high"]), "高点之后下跌天数"),
            ("hk.up_days", float(metrics["up_days"]), "区间上涨天数"),
            ("hk.down_days", float(metrics["down_days"]), "区间下跌天数"),
        ]
        for row, change in zip(sessions, changes):
            ledger.append((f"hk.day.{row['session_date']}.change_pct", change, f"{row['session_date']} 单日涨跌"))
            ledger.append((f"hk.day.{row['session_date']}.turnover", row["turnover_hkd"], f"{row['session_date']} 成交额"))
            ledger.append((f"hk.day.{row['session_date']}.close", row["index_close"], f"{row['session_date']} 收市"))
        metrics["ledger"] = ledger

    if filings:
        themes: dict[str, list[dict]] = {}
        for row in filings:
            themes.setdefault(row.get("theme", "其他"), []).append(row)
        same_day: dict[str, list[dict]] = {}
        for row in filings:
            same_day.setdefault(row["published"].strftime("%Y-%m-%d"), []).append(row)
        busiest = max(same_day.items(), key=lambda item: len(item[1]))
        metrics.update({
            "issuers": len(filings),
            "themes": {theme: len(rows) for theme, rows in themes.items()},
            "busiest_date": busiest[0],
            "busiest_count": len(busiest[1]),
            "category_counts": _count_categories(filings),
        })
        total_filings = sum(row.get("filing_count", 1) for row in filings)
        metrics["total_filings"] = total_filings
        metrics["ledger"].extend([
            ("filings.issuers", float(len(filings)), "本期公告覆盖的发行人数"),
            ("filings.total_filings", float(total_filings), "本期公告份数合计"),
            ("filings.themes", float(len(themes)), "本期覆盖的细分主题数"),
            ("filings.busiest_count", float(len(busiest[1])), "单日公告最集中的发行人数"),
        ])
    else:
        metrics.update({"issuers": 0, "themes": {}, "busiest_date": None, "busiest_count": 0, "category_counts": {}})

    return metrics


def _count_categories(filings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in filings:
        for label in row.get("categories", []):
            counts[label] = counts.get(label, 0) + 1
    return counts


def ledger_values(metrics: dict) -> list[float]:
    values: list[float] = []
    for _key, value, _label in metrics.get("ledger", []):
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def describe(metrics: dict) -> str:
    """把关键指标整理成模型可读的事实块（不含任何猜测）。"""
    if not metrics.get("has_quote"):
        return "本期无交易所行情数据。"
    lines = [
        f"交易日数 {metrics['sessions']}，区间 {metrics['first_session']} 至 {metrics['last_session']}。",
        f"恒生指数：基准前收 {S.fmt_index(metrics['base_prev'])}，最新收市 {S.fmt_index(metrics['close'])}，"
        f"周涨跌 {S.fmt_pct(metrics['week_change_pct'])}（{S.fmt_points(metrics['week_change_points'])}）。",
        f"周内最高 {S.fmt_index(metrics['high'])}（{metrics['high_date']}），最低 {S.fmt_index(metrics['low'])}"
        f"（{metrics['low_date']}），振幅 {S.fmt_pct(metrics['amplitude_pct'], signed=False)}，"
        f"自高点回落 {S.fmt_pct(metrics['drawdown_from_high_pct'])}，高点后下跌 {metrics['down_days_after_high']} 日。",
        f"主板成交额：首日 {S.fmt_turnover(metrics['turnover_first'])}，末日 {S.fmt_turnover(metrics['turnover_last'])}，"
        f"日均 {S.fmt_turnover(metrics['turnover_avg'])}，末日较首日 {S.fmt_pct(metrics['turnover_change_pct'])}。",
        "逐日：" + "；".join(
            f"{row['session_date']} 成交额 {S.fmt_turnover(row['turnover_hkd'])}、收市 {S.fmt_index(row['index_close'])}"
            for row in metrics.get("daily", [])
        ) if metrics.get("daily") else "",
    ]
    return "\n".join(line for line in lines if line)


def annotate_daily(metrics: dict, quotes: list[dict]) -> None:
    """行情条目在这之后才拿到来源编号，逐日记录需要回填 id 以便溯源。"""
    ordered = sorted(quotes, key=lambda r: r["session_date"])
    metrics["daily"] = [
        {"session_date": row["session_date"], "turnover_hkd": row["turnover_hkd"],
         "index_close": row["index_close"], "source_id": row.get("id")}
        for row in ordered
    ]
    metrics["quote_ids"] = [row.get("id") for row in ordered if row.get("id")]


def now_window_note(metrics: dict, period_end: dt.datetime) -> str:
    if not metrics.get("has_quote"):
        return ""
    through = dt.date.fromisoformat(metrics["data_through"])
    if through < period_end.date():
        return f"行情数据截至 {through.isoformat()} 收市，区间内后续交易日数据未计入。"
    return ""
