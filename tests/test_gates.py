#!/usr/bin/env python3
"""闸门自测：不联网，用构造数据验证校验层是否真的会拦。

运行：python tests/test_gates.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wr import metrics as M, settings as S, validate as V  # noqa: E402

PASSED: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
    except AssertionError as exc:
        print(f"FAIL {name}: {exc}")
        raise SystemExit(1)
    PASSED.append(name)
    print(f"PASS {name}")


def base_report() -> dict:
    return {
        "headline": "测试标题",
        "overview": "恒生指数本周收于 22,958.65，较上周下跌 0.58%。",
        "overview_source_ids": ["S01"],
        "ashare": {"summary": "公告若干。", "summary_source_ids": ["S01"], "drivers": []},
        "hk": {"summary": "行情若干。", "summary_source_ids": ["S01"], "drivers": []},
        "highlights": [{"market": "港股", "category": "市场结构", "title": "回落",
                        "reported": "收市 22,958.65。", "analysis": "区间震荡。", "watch": "看成交额。",
                        "source_ids": ["S01"], "metric_ids": ["m:hk.close"]}],
        "other_updates": [],
        "next_watch": [{"text": "2026-10-31 三季度报告披露截止", "basis": "日历规则：q3_report"}],
    }


LEDGER_ARGS = ([22958.65, -0.58, 31.0], ["恒生指数收市 22,958.65，前收市 23,093.37。"],
               {"start": "2026-10-26 09:30", "end": "2026-10-30 11:54", "label": "x", "edition": "2026-W44"})


def ledger() -> V.Ledger:
    return V.Ledger(*LEDGER_ARGS)


def test_forbidden() -> None:
    report = base_report()
    report["highlights"][0]["analysis"] = "具备翻倍空间，建议买入。"
    try:
        V.enforce_forbidden(report)
    except V.ReportError as exc:
        assert "翻倍" in str(exc), exc
        return
    raise AssertionError("禁语未被拦截")


def test_fabricated_number() -> None:
    report = base_report()
    report["highlights"][0]["reported"] = "单日成交额达到 4,321 亿港元。"
    try:
        V.enforce_numbers(report, ledger())
    except V.ReportError as exc:
        assert "4321" in str(exc).replace(",", ""), exc
        return
    raise AssertionError("伪造数字未被拦截")


def test_ledger_number_allowed() -> None:
    report = base_report()
    report["highlights"][0]["reported"] = "收市 22,958.65，周涨跌 -0.58%。"
    V.enforce_numbers(report, ledger())


def test_overview_without_number() -> None:
    report = base_report()
    report["overview"] = "本期市场表现平稳，详见下文。"
    try:
        V.check_overview(report)
    except V.ReportError as exc:
        assert "OVERVIEW_WITHOUT_NUMBER" in str(exc), exc
        return
    raise AssertionError("无数值的概览未被拦截")


def test_overview_meta_narration() -> None:
    report = base_report()
    report["overview"] = "本周涨幅 0.5%，具体记录见下文。"
    try:
        V.check_overview(report)
    except V.ReportError as exc:
        assert "OVERVIEW_META_NARRATION" in str(exc), exc
        return
    raise AssertionError("元叙述概览未被拦截")


def test_missing_provenance() -> None:
    report = base_report()
    report["highlights"][0].pop("source_ids")
    report["highlights"][0].pop("metric_ids")
    try:
        V.validate_schema(report, {"S01"})
    except V.ReportError as exc:
        assert "溯源" in str(exc), exc
        return
    raise AssertionError("无溯源的判断未被拦截")


def test_unknown_metric() -> None:
    report = base_report()
    report["highlights"][0]["metric_ids"] = ["m:hk.not_exist"]
    try:
        V.check_metric_ids(report, {"m:hk.close"})
    except V.ReportError as exc:
        assert "not_exist" in str(exc), exc
        return
    raise AssertionError("伪造指标编号未被拦截")


def test_unknown_source() -> None:
    report = base_report()
    report["overview_source_ids"] = ["S99"]
    try:
        V.validate_schema(report, {"S01"})
    except V.ReportError as exc:
        assert "S99" in str(exc), exc
        return
    raise AssertionError("未知来源编号未被拦截")


def test_minimum_judgement() -> None:
    report = base_report()
    report["highlights"] = []
    try:
        V.enforce_minimum(report, {"has_quote": True, "sessions": 4})
    except V.ReportError as exc:
        assert "NO_JUDGEMENT" in str(exc), exc
        return
    raise AssertionError("无判断条目未被拦截")


def test_issue_window_monday_anchor() -> None:
    monday = dt.datetime(2026, 10, 26, 9, 30, tzinfo=S.SHANGHAI)
    window = S.issue_window(monday)
    assert window["start"].date() == dt.date(2026, 10, 19), window["start"]
    assert window["end"] == monday, window["end"]
    assert window["edition"] == "2026-W43", window["edition"]


def test_issue_window_midweek() -> None:
    friday = dt.datetime(2026, 10, 30, 11, 54, tzinfo=S.SHANGHAI)
    window = S.issue_window(friday)
    assert window["start"].date() == dt.date(2026, 10, 26), window["start"]
    assert window["end"] == friday
    assert window["edition"] == "2026-W44"
    assert window["partial"] is True


def test_metrics_direction() -> None:
    quotes = [
        {"session_date": "2026-10-23", "turnover_hkd": 2497.8e8, "index_close": 23093.37, "index_prev": 22934.68},
        {"session_date": "2026-10-26", "turnover_hkd": 1757.6e8, "index_close": 23211.81, "index_prev": 23093.37},
        {"session_date": "2026-10-29", "turnover_hkd": 1894.5e8, "index_close": 22958.65, "index_prev": 23094.83},
    ]
    m = M.build_metrics(quotes, [])
    assert abs(m["week_change_pct"] - 0.1045) < 0.01, m["week_change_pct"]
    assert abs(m["drawdown_from_high_pct"] + 1.0906) < 0.01, m["drawdown_from_high_pct"]
    assert abs(m["amplitude_pct"] - 1.1034) < 0.01, m["amplitude_pct"]
    assert m["turnover_change_pct"] < -20


def test_model_payload_serializable() -> None:
    """模型请求体必须能直接 json 序列化，避免上线后才发现 datetime 泄漏。"""
    import json

    from wr import llm

    now = dt.datetime(2026, 10, 30, 11, 54, tzinfo=S.SHANGHAI)
    window = S.issue_window(now)
    items = [{"id": "S01", "market": "港股", "channel": "quote", "title": "行情",
              "published": now, "date_only": True, "source": "香港交易所",
              "source_tier_label": "港交所官方行情", "url": "https://example.com/a", "snippet": "摘要"}]
    body = llm.payload(items, "指标块", [{"id": "m:hk.close", "label": "收市"}], window, None)
    text = json.dumps(body, ensure_ascii=False)
    assert "2026-10-26" in text and "Asia/Shanghai" not in text


def test_update_requires_note() -> None:
    report = base_report()
    report["other_updates"] = [{"market": "A股", "category": "定期报告", "title": "某公司三季报",
                                "reported": "某公司披露三季度报告。", "source_ids": ["S01"]}]
    try:
        V.validate_schema(report, {"S01"})
    except V.ReportError as exc:
        assert "note" in str(exc), exc
        return
    raise AssertionError("其他动态缺小结未被拦截")


def test_update_note_passes() -> None:
    report = base_report()
    report["other_updates"] = [{"market": "A股", "category": "定期报告", "title": "某公司三季报",
                                "reported": "某公司披露三季度报告。",
                                "note": "半导体设计板块本期另有他标的披露，属板块性节奏。",
                                "source_ids": ["S01"]}]
    V.validate_schema(report, {"S01"})


def test_source_link_clickable():
    from wr import render

    sources = {"S11": {"source": "巨潮资讯网", "url": "https://static.cninfo.com.cn/a.PDF"}}
    html = render.source_line(["S11"], sources)
    assert 'href="https://static.cninfo.com.cn/a.PDF"' in html, html
    assert "target=\"_blank\"" in html, html
    assert 'rel="noopener noreferrer"' in html, html


def test_source_without_url_stays_text():
    from wr import render

    html = render.source_line(["S11"], {"S11": {"source": "巨潮资讯网"}})
    assert "<a " not in html, html


def main() -> None:
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            check(name, fn)
    print(f"\n{len(PASSED)} 项通过")


if __name__ == "__main__":
    main()
