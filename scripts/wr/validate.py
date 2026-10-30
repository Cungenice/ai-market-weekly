"""校验层：schema、溯源、数字台账、禁语。

三道检查，任何一道不过都阻断发布（fail-closed）：
1. 结构：字段齐全、类型正确、每条陈述都有溯源（来源 / 计算 / 日历）。
2. 数字：正文出现的每个数字必须能在「引用来源原文 ∪ 计算台账 ∪ 年份 ∪ 序号」中找到。
3. 合规：禁语、必需的 AI 标识与免责要素。
"""

from __future__ import annotations

import re

from . import settings as S


class ReportError(RuntimeError):
    pass


REQUIRED_FIELDS = ("headline", "overview", "overview_source_ids", "ashare", "hk",
                   "highlights", "other_updates", "next_watch")
PROVENANCE_FIELDS = ("source_ids", "metric_ids", "basis")


def _require_list(report: dict, field: str) -> list:
    value = report.get(field)
    if not isinstance(value, list):
        raise ReportError(f"{field} 必须是数组")
    return value


def validate_schema(report: dict, valid_source_ids: set[str]) -> None:
    if not isinstance(report, dict):
        raise ReportError("报告必须是 JSON 对象")
    for field in REQUIRED_FIELDS:
        if field not in report:
            raise ReportError(f"缺少必需字段：{field}")
    for field in ("headline", "overview"):
        if not isinstance(report.get(field), str) or not report[field].strip():
            raise ReportError(f"{field} 必须是非空文本")
    for field in ("highlights", "other_updates", "next_watch"):
        _require_list(report, field)

    _check_ids(report.get("overview_source_ids"), valid_source_ids, "overview_source_ids", allow_empty=True)
    for key in ("ashare", "hk"):
        section = report.get(key)
        if not isinstance(section, dict) or not isinstance(section.get("drivers"), list):
            raise ReportError(f"{key} 必须包含 summary 与 drivers 数组")
        _check_ids(section.get("summary_source_ids"), valid_source_ids, f"{key}.summary_source_ids", allow_empty=True)
        for driver in section["drivers"]:
            if not isinstance(driver, dict) or not str(driver.get("text", "")).strip():
                raise ReportError(f"{key}.drivers 条目必须包含 text")
            _check_provenance(driver, valid_source_ids, f"{key}.drivers")

    for group in ("highlights", "other_updates"):
        for story in report[group]:
            if not isinstance(story, dict):
                raise ReportError(f"{group} 的每个条目必须是对象")
            fields = ("market", "category", "title", "reported")
            if group == "highlights":
                fields += ("analysis", "watch")
            for field in fields:
                if not isinstance(story.get(field), str) or not story[field].strip():
                    raise ReportError(f"{group}.{field} 必须是非空文本")
            _check_provenance(story, valid_source_ids, f"{group}.{story.get('title', '(无标题)')}")

    for item in report["next_watch"]:
        if not isinstance(item, dict) or not str(item.get("text", "")).strip():
            raise ReportError("next_watch 条目必须包含 text")
        _check_provenance(item, valid_source_ids, "next_watch")

    for row in report.get("previous_check", []) or []:
        if row.get("status") not in {"兑现", "未兑现", "待验证"}:
            raise ReportError(f"previous_check 状态非法：{row.get('status')!r}")


def _check_ids(ids: object, valid: set[str], label: str, allow_empty: bool = False) -> None:
    if ids is None:
        if allow_empty:
            return
        raise ReportError(f"{label} 缺失")
    if not isinstance(ids, list):
        raise ReportError(f"{label} 必须是数组")
    if not ids and not allow_empty:
        raise ReportError(f"{label} 不能为空")
    unknown = [sid for sid in ids if sid not in valid]
    if unknown:
        raise ReportError(f"{label} 引用了不存在的来源编号：{unknown}")


def _check_provenance(item: dict, valid: set[str], label: str) -> None:
    ids = item.get("source_ids") or []
    metrics = item.get("metric_ids") or []
    basis = str(item.get("basis") or "").strip()
    _check_ids(ids, valid, f"{label}.source_ids", allow_empty=True)
    if not ids and not metrics and not basis:
        raise ReportError(f"{label} 没有任何溯源（source_ids / metric_ids / basis 全为空）")


# ---------------------------------------------------------------- 数字台账


class Ledger:
    """允许出现的数字集合：来源原文、计算台账、日期与序号。"""

    def __init__(self, ledger_values: list[float], source_texts: list[str], period: dict):
        self.allowed: set[float] = set()
        self.raw_count = 0
        for value in ledger_values:
            self._add_variants(float(value))
        for text in source_texts:
            for value in S.number_tokens(text):
                self.allowed.add(round(value, 4))
                self.raw_count += 1
        for key in ("start", "end"):
            for value in S.number_tokens(str(period.get(key, ""))):
                self.allowed.add(round(value, 4))
        low, high = S.cfg("validation.allow_year_range", [1990, 2100])
        self.year_range = (int(low), int(high))
        self.ordinal_max = float(S.cfg("validation.ordinal_max", 20))
        self.tolerance = float(S.cfg("validation.number_tolerance_abs", 0.06))

    def _add_variants(self, value: float) -> None:
        variants = {value, abs(value)}
        for scale in (1e8, 1e4, 1e12):
            for sign in (1, -1):
                scaled = value * sign / scale
                variants.update({scaled, abs(scaled)})
        for item in list(variants):
            for digits in (0, 1, 2):
                variants.add(round(item, digits))
        self.allowed.update(round(item, 4) for item in variants if abs(item) < 1e13)

    def allows(self, value: float) -> bool:
        if value in self.allowed:
            return True
        if value == int(value):
            if self.year_range[0] <= value <= self.year_range[1]:
                return True
            if 0 <= value <= self.ordinal_max:
                return True
        for candidate in self.allowed:
            if abs(candidate - value) <= self.tolerance:
                return True
        return False


def verify_numbers(report: dict, ledger: Ledger) -> list[str]:
    problems: list[str] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in PROVENANCE_FIELDS:
                    continue
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            for token in S.number_tokens(value):
                if not ledger.allows(token):
                    problems.append(f"{path} 出现无法核对的数字：{token:g}")

    walk(report, "report")
    return problems


def enforce_numbers(report: dict, ledger: Ledger) -> None:
    problems = verify_numbers(report, ledger)
    if problems:
        raise ReportError("UNVERIFIED_NUMBER: " + "；".join(problems[:8]))


# ---------------------------------------------------------------- 合规


def scan_forbidden(report: dict) -> list[str]:
    phrases = S.forbidden_phrases()
    hits: list[str] = []

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str):
            for phrase in phrases:
                if phrase in value:
                    hits.append(f"{path} 命中禁语「{phrase}」")

    walk(report, "report")
    return hits


def enforce_forbidden(report: dict) -> None:
    hits = scan_forbidden(report)
    if hits:
        raise ReportError("FORBIDDEN_PHRASE: " + "；".join(hits[:6]))


def check_overview(report: dict) -> None:
    if not S.cfg("validation.overview_requires_number", True):
        return
    overview = report.get("overview", "")
    if not S.number_tokens(overview):
        raise ReportError("OVERVIEW_WITHOUT_NUMBER: 概览段必须包含至少一个可核对的数值命题")
    meta_phrases = ("见下文", "见其他动态", "具体记录见", "本期暂无")
    for phrase in meta_phrases:
        if phrase in overview:
            raise ReportError(f"OVERVIEW_META_NARRATION: 概览段出现「{phrase}」，应描述市场而非描述本文档")


# ---------------------------------------------------------------- 质量过滤


def enforce_minimum(report: dict, metrics: dict) -> None:
    minimum = int(S.cfg("validation.min_highlights", 1))
    if len(report.get("highlights") or []) >= minimum:
        return
    if metrics.get("has_quote") and metrics.get("sessions", 0) >= 2:
        raise ReportError("NO_JUDGEMENT: 行情数据充足但未形成任何判断条目")
    raise ReportError("NO_JUDGEMENT: 本期无法形成有效判断，请检查采集覆盖")


def dedupe(items: list[dict], key_fields=("title",)) -> list[dict]:
    kept: list[dict] = []
    for item in items:
        text = " ".join(str(item.get(field, "")) for field in key_fields)
        if any(S.title_similarity(text, " ".join(str(other.get(field, "")) for field in key_fields)) >= 0.6
               for other in kept):
            continue
        kept.append(item)
    return kept


def check_metric_ids(report: dict, valid_metrics: set[str]) -> None:
    """metric_ids 必须指向台账里真实存在的键，否则视为伪造依据。"""

    def walk(value, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "metric_ids":
                    for mid in child or []:
                        if mid not in valid_metrics:
                            raise ReportError(f"{path}.metric_ids 引用了不存在的指标：{mid}")
                else:
                    walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(report, "report")


def enforce_headline(report: dict) -> None:
    limit = int(S.cfg("validation.max_headline_chars", 46))
    if len(report.get("headline", "")) > limit:
        raise ReportError(f"HEADLINE_TOO_LONG: 超过 {limit} 字")
