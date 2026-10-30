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


def test_restatement_is_rejected() -> None:
    """「谁在哪天发布了什么」的公告转述必须被拦下，否则正文退回通稿。"""
    report = base_report()
    report["other_updates"] = [{
        "market": "A股", "category": "定期报告", "title": "金山办公、中科创达披露三季度报告",
        "reported": "金山办公（688111）于2026年10月28日披露2026年第三季度报告；"
                    "中科创达（300496）同日披露2026年三季度报告。",
        "note": "两家同为软件与应用层公司。", "source_ids": ["S01"]}]
    try:
        V.enforce_framing(report)
    except V.ReportError as exc:
        assert "RESTATEMENT_WITHOUT_INSIGHT" in str(exc), exc
        return
    raise AssertionError("公告转述未被拦截")


def test_roster_restatement_is_rejected() -> None:
    """只罗列谁披露了同一份报告，即便没有「于…披露」句式也要拦。"""
    report = base_report()
    report["highlights"][0]["reported"] = (
        "2026年10月27日至10月30日，紫光国微、中兴通讯、韦尔股份、深信服、天孚通信、浪潮信息、"
        "金山办公、中科创达、北京君正、沪电股份、华润微、工业富联等发行人相继披露2026年"
        "第三季度报告或三季度报告。")
    try:
        V.enforce_framing(report)
    except V.ReportError as exc:
        assert "RESTATEMENT_WITHOUT_INSIGHT" in str(exc), exc
        return
    raise AssertionError("公告名单罗列未被拦截")


def test_disclosure_reading_passes() -> None:
    report = base_report()
    report["other_updates"] = [{
        "market": "A股", "category": "定期报告", "title": "软件与应用层两家披露三季度报告",
        "reported": "两家同为软件与应用层标的，本期与半导体、光模块同批落地，"
                    "说明这是同一财报窗口的组成部分而非孤立事件；这类公告可读的是"
                    "报告期收入结构与费用端的变化方向，而非标题本身。",
        "note": "同批标的已构成对照样本；看收入结构是否随 AI 订单兑现而改变。",
        "source_ids": ["S01"]}]
    V.enforce_framing(report)


def test_rule_narrative_passes_framing() -> None:
    """规则兜底版本也必须过同一道框架检查，否则模型不可用时会退回通稿。"""
    from wr import narrative

    def filing(rid, name, code, theme, published, categories, glosses):
        return {"id": rid, "market": "A股", "issuer_name": name, "issuer_code": code,
                "theme": theme, "published": published, "categories": categories,
                "glosses": glosses, "filing_count": 1, "announcements": []}

    filings = [
        filing("S01", "金山办公", "688111", "AI 应用", "2026-10-28T18:00", ["定期报告"],
               ["把报告期的经营与财务数据推到公开口径"]),
        filing("S02", "中科创达", "300496", "AI 应用", "2026-10-28T19:00", ["定期报告"],
               ["把报告期的经营与财务数据推到公开口径"]),
        filing("S03", "紫光国微", "002049", "半导体设计", "2026-10-28T20:00", ["定期报告"],
               ["把报告期的经营与财务数据推到公开口径"]),
    ]
    report = {"headline": "测试", "overview": "行情有数。",
              "highlights": [], "other_updates": narrative._other_updates(filings)}
    V.enforce_framing(report)
    assert report["other_updates"], "其他动态为空"
    for row in report["other_updates"]:
        assert row["note"].strip(), row
        assert "披露2026年" not in row["reported"], row["reported"]


def intel_row(**kwargs) -> dict:
    row = {"thread": "产业政策", "attribute": "政策发布", "track": "official",
           "title": "某部委印发人工智能产业支持措施", "note": "政策原件已发布，可读的是适用对象与支持方式",
           "source_ids": ["S01"]}
    row.update(kwargs)
    return row


def test_intel_thread_enum() -> None:
    report = base_report()
    report["intel"] = [intel_row(thread="产业风向")]
    try:
        V.enforce_intel(report)
    except V.ReportError as exc:
        assert "INTEL_THREAD_INVALID" in str(exc), exc
        return
    raise AssertionError("枚举外的知识脉络未被拦截")


def test_intel_irrelevant_must_not_render() -> None:
    report = base_report()
    report["intel"] = [intel_row(thread="其他", attribute="其他")]
    try:
        V.enforce_intel(report)
    except V.ReportError as exc:
        assert "INTEL_IRRELEVANT_KEPT" in str(exc), exc
        return
    raise AssertionError("判为「其他」的舆情条目进入了页面")


def test_intel_note_required() -> None:
    report = base_report()
    report["intel"] = [intel_row(note=" ")]
    try:
        V.enforce_intel(report)
    except V.ReportError as exc:
        assert "INTEL_WITHOUT_NOTE" in str(exc), exc
        return
    raise AssertionError("缺少研判句的舆情条目未被拦截")


def test_intel_prefilter_and_tracks() -> None:
    from wr import intel as I

    assert I.track_of_host("miit.gov.cn") == "official"
    assert I.track_of_host("dzwxf.mofcom.gov.cn") == "official"
    assert I.track_of_host("m.caixin.com") == "media"
    assert I.track_of_host("example.com") is None
    # AI 主体 + 产业事件才收；招聘、观点稿、海外宏观噪音一律不收
    assert I.prefilter("工信部印发人工智能算力基础设施行动方案", "")
    assert not I.prefilter("某AI公司校园招聘启动", "")
    assert not I.prefilter("人工智能板块或将迎来反弹", "")
    assert not I.prefilter("人工智能相关美债发行升温", "")


def test_intel_cap_limits_media_share() -> None:
    import datetime as dt
    from wr import intel as I

    rows = []
    for index in range(12):
        rows.append({"thread": "重要产业动态", "track": "media" if index % 2 else "official",
                     "published": dt.datetime(2026, 10, 20, 9, index), "title": f"t{index}"})
    kept = I.cap(rows)
    assert len(kept) <= 12, len(kept)
    media = sum(1 for row in kept if row["track"] == "media")
    assert media <= max(1, int(12 * 0.6)), media


def test_takeaway_has_no_white_panel() -> None:
    css = (ROOT / "scripts" / "wr" / "assets" / "site.css").read_text(encoding="utf-8")
    block = css.split(".update .takeaway{", 1)[1].split("}", 1)[0]
    assert "background:#fff" not in block, block
    assert "background:none" in block or "background:transparent" in block, block


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
