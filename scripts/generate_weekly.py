#!/usr/bin/env python3
"""A/H AI 市场周报生成器。

流程：四通道采集 → 计算派生指标 → 模型或规则叙事 → 三道校验 → 渲染发布。
任何一环失败都按「事实闸门阻断、结构闸门降级」处理：数字对不上就不发，
素材不足就出精简版，而不是整期停更。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from wr import collect, intel as intel_labels, llm, metrics as M, narrative, render, settings as S, validate as V  # noqa: E402


def log(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def assign_ids(filings: list[dict], quotes: list[dict], clues: list[dict],
               intel_items: list[dict] | None = None) -> list[dict]:
    filings.sort(key=lambda row: (row["published"], row["issuer_code"]), reverse=True)
    ordered = filings + quotes + clues + (intel_items or [])
    for index, item in enumerate(ordered, 1):
        item["id"] = f"S{index:02d}"
    return ordered


def metric_catalog(metrics: dict) -> list[dict]:
    """对外暴露的指标编号统一加 m: 前缀，与正文引用一一对应。"""
    return [{"id": f"m:{key}", "label": label} for key, _value, label in metrics.get("ledger", [])]


def load_previous(edition: str) -> dict | None:
    index_path = ROOT / "data" / "archives.json"
    if not index_path.exists():
        return None
    try:
        entries = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    for entry in entries:
        key = entry.get("edition") or entry.get("date")
        if key and key != edition:
            path = ROOT / "weekly" / f"{key}.json"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    return None
    return None


def build_report(items: list[dict], filings: list[dict], metrics: dict, calendar_events: list[dict],
                 period: dict, previous: dict | None, allow_model: bool,
                 intel_items: list[dict] | None = None) -> tuple[dict, str, list[dict]]:
    report: dict | None = None
    notes: list[dict] = []
    mode = "rule"
    intel_items = intel_items or []
    if allow_model and items:
        catalog = metric_catalog(metrics)
        block = M.describe(metrics)
        feedback = None
        for attempt in (1, 2):
            try:
                candidate = llm.draft(items, block, catalog, period, previous, feedback, intel_items)
                candidate.setdefault("next_watch", _calendar_watch(calendar_events))
                candidate["previous_check"] = candidate.get("previous_check") or narrative.previous_check(previous)
                hydrate_intel(candidate, intel_items)
                _validate_all(candidate, items, metrics, period, calendar_events)
                report, mode = candidate, "model"
                notes.append({"attempt": attempt, "result": "accepted"})
                log({"stage": "model", "attempt": attempt, "result": "accepted"})
                break
            except V.ReportError as exc:
                feedback = str(exc)[:1200]
                notes.append({"attempt": attempt, "result": "rejected", "reason": feedback})
                log({"stage": "model", "attempt": attempt, "result": "rejected", "reason": feedback})
            except RuntimeError as exc:
                notes.append({"attempt": attempt, "result": "unavailable", "reason": str(exc)[:400]})
                log({"stage": "model", "attempt": attempt, "result": "unavailable", "reason": str(exc)[:400]})
                break
    if report is None:
        report = narrative.build(metrics, filings, calendar_events, period, previous, intel_items)
        report["next_watch"] = _calendar_watch(calendar_events)
        report["previous_check"] = narrative.previous_check(previous)
        _validate_all(report, items, metrics, period, calendar_events)
        mode = "rule"
        notes.append({"result": "fallback", "mode": "rule"})
    return report, mode, notes


def hydrate_intel(report: dict, intel_items: list[dict]) -> None:
    """把模型给的标签落回采集条目，轨道与时间由代码决定，不由模型自述。"""
    by_id = {item["id"]: item for item in intel_items}
    threads = set(intel_labels.thread_labels())
    rows: list[dict] = []
    for row in report.get("intel") or []:
        if str(row.get("relevance") or "related") == "other":
            continue
        sid = (row.get("source_ids") or [None])[0]
        src = by_id.get(sid)
        if src is None:
            continue
        track = str(src.get("track") or "media")
        thread = str(row.get("thread") or src.get("thread") or "重要产业动态")
        if thread not in threads:
            thread = str(src.get("thread") or "重要产业动态")
        rows.append({
            "thread": thread,
            "attribute": str(row.get("attribute") or src.get("attribute") or "其他"),
            "track": track,
            "track_label": intel_labels.TRACK_LABELS.get(track, "白名单媒体"),
            "title": str(row.get("title") or src.get("title") or "").strip(),
            "note": str(row.get("note") or intel_labels.rule_note({**src, "thread": thread})).strip(),
            "published": src["published"].isoformat(timespec="minutes"),
            "caveat": track == "media" and thread in set(S.cfg("intel.official_required_threads", []) or []),
            "source_ids": [sid],
        })
    report["intel"] = rows


def _calendar_watch(calendar_events: list[dict]) -> list[dict]:
    return narrative.calendar_watch(calendar_events)


def _validate_all(report: dict, items: list[dict], metrics: dict, period: dict,
                  calendar_events: list[dict]) -> None:
    valid_ids = {item["id"] for item in items}
    V.validate_schema(report, valid_ids)
    V.check_metric_ids(report, {entry["id"] for entry in metric_catalog(metrics)})
    V.enforce_headline(report)
    V.enforce_framing(report)
    V.enforce_intel(report)
    V.enforce_forbidden(report)
    V.check_overview(report)
    ledger = V.Ledger(M.ledger_values(metrics),
                      [f"{item.get('title', '')} {item.get('snippet', '')}" for item in items]
                      + [str(entry.get("date", "")) for entry in calendar_events]
                      + [str(entry.get("date_end", "")) for entry in calendar_events]
                      + [str(entry.get("text", "")) for entry in report.get("next_watch", [])]
                      + [period.get("label", ""), period.get("edition", "")],
                      period)
    V.enforce_numbers(report, ledger)
    V.enforce_minimum(report, metrics)


def write_outputs(base: Path, report: dict, items: list[dict], period: dict, metrics: dict,
                  generated: dt.datetime, mode: str, coverage: list[dict],
                  model_notes: list[dict] | None = None) -> Path:
    edition = period["edition"]
    (base / "weekly").mkdir(parents=True, exist_ok=True)
    (base / "data").mkdir(parents=True, exist_ok=True)
    homepage = render.render_report(report, items, period, metrics, generated, "weekly/")
    archived = render.render_report(report, items, period, metrics, generated, "./")
    (base / "index.html").write_text(homepage, encoding="utf-8")
    (base / "weekly" / f"{edition}.html").write_text(archived, encoding="utf-8")
    payload = {
        "edition": edition,
        "date": period["start"].date().isoformat(),
        "week": period["week"],
        "period": {"start": period["start"].strftime("%Y-%m-%d %H:%M"),
                   "end": period["end"].strftime("%Y-%m-%d %H:%M")},
        "headline": report["headline"],
        "overview": report["overview"],
        "mode": mode,
        "generated_at": generated.isoformat(),
        "data_through": metrics.get("data_through"),
        "report": report,
        "metrics": {key: value for key, value in metrics.items() if key not in {"ledger", "daily"}},
        "ledger": [{"id": key, "label": label, "value": value} for key, value, label in metrics.get("ledger", [])],
        "coverage": coverage,
        "model_attempts": model_notes or [],
        "sources": [{**item, "published": item["published"].isoformat(timespec="minutes")} for item in items],
    }
    (base / "weekly" / f"{edition}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = base / "data" / "archives.json"
    existing = []
    if index_path.exists():
        try:
            existing = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    entry = {
        "edition": edition,
        "label": edition,
        "date": payload["date"],
        "week_label": f"W{period['week']:02d}",
        "sort_value": f"{period['end']:%Y-%m-%dT%H:%M}",
        "period": f"{payload['period']['start']} — {payload['period']['end']}",
        "headline": report["headline"],
        "overview": report["overview"],
    }
    entries = [row for row in existing if (row.get("edition") or row.get("date")) != edition]
    entries.append(entry)
    entries.sort(key=lambda row: str(row.get("sort_value") or (str(row.get("date", "")) + "T00:00")),
                 reverse=True)
    index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (base / "weekly" / "index.html").write_text(render.render_archive(entries), encoding="utf-8")
    return base / "weekly" / f"{edition}.html"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 A/H AI 市场周报")
    parser.add_argument("--dry-run", action="store_true", help="写入 preview/，不覆盖已发布文件")
    parser.add_argument("--no-model", action="store_true", help="跳过模型，仅用规则叙事")
    parser.add_argument("--out", default=None, help="输出根目录（默认仓库根目录）")
    args = parser.parse_args()

    now = dt.datetime.now(S.SHANGHAI).replace(second=0, microsecond=0)
    period = S.issue_window(now)
    log({"stage": "start", "edition": period["edition"], "window": period["label"]})

    filings, f_status = collect.collect_filings(period["start"], period["end"])
    quotes, q_status = collect.collect_quotes(period["start"], period["end"])
    clues, c_status = collect.collect_clues(period["start"], period["end"])
    intel_items, i_status = collect.collect_intel(period["start"], period["end"])
    calendar_events, k_status = collect.collect_calendar(now)
    coverage = [f_status, q_status, c_status, i_status, k_status]
    for status in coverage:
        log({"stage": "coverage", **status})

    if not quotes and not filings and not intel_items:
        raise RuntimeError("NO_ELIGIBLE_ITEMS: 公告、行情与舆情三条通道均为空，本期无材料可用")

    items = assign_ids(filings, quotes, clues, intel_items)
    metrics = M.build_metrics(quotes, filings)
    M.annotate_daily(metrics, quotes)
    log({"stage": "metrics", "sessions": metrics.get("sessions", 0), "issuers": metrics.get("issuers", 0),
         "ledger_entries": len(metrics.get("ledger", []))})

    previous = load_previous(period["edition"])
    report, mode, model_notes = build_report(items, filings, metrics, calendar_events, period, previous,
                                             allow_model=not args.no_model, intel_items=intel_items)
    log({"stage": "report", "mode": mode, "highlights": len(report.get("highlights", [])),
         "intel": len(report.get("intel", [])),
         "other_updates": len(report.get("other_updates", [])), "calendar": len(report.get("next_watch", []))})

    base = Path(args.out) if args.out else (ROOT / "preview" if args.dry_run else ROOT)
    if base.exists() and base.name == "preview":
        shutil.rmtree(base)
    written = write_outputs(base, report, items, period, metrics, now, mode, coverage, model_notes)
    log({"stage": "done", "written": str(written.relative_to(ROOT)) if written.is_relative_to(ROOT) else str(written)})


if __name__ == "__main__":
    trace_id = uuid.uuid4().hex
    print(f"trace_id={trace_id} state=collecting", flush=True)
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"::error::trace_id={trace_id} state=blocked {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
    print(f"trace_id={trace_id} state=checked publication_files_ready", flush=True)
