"""
source_registry.py — 信源登记表加载、内容路由与字段级断言

配套文件: sources.yaml (schema: wr-sources/v1)

设计要点
--------
1. 分层即策略: L1 才可写"确认"，L3 需二次核，L4 只做线索（clue_only）。
2. 授权先于抓取: license / redistribution 在路由阶段就被检查，不留给发稿时想起来。
3. 冲突从严: source 级配置只能比 tier_policy 更严，lint 会拦截放宽。
4. 断言前移: 抓取层解析完立即跑 assert_record，不把脏数据留到生成层。

常用命令
--------
    python source_registry.py lint
    python source_registry.py route company_fact
    python source_registry.py policy wind
    python source_registry.py selftest
    python source_registry.py export-json routes.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖: python -m pip install pyyaml")

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "sources.yaml"

REQUIRED_SOURCE_KEYS = {"id", "name", "tier", "kind", "content_types", "endpoint"}
VALID_TIERS = {"L1", "L2", "L3", "L4"}
# 强度排序：数值越大越严
RESTRICTION_ORDER = {
    "attribution_required": 1,
    "forbidden": 2,
}


class RegistryError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #
def load(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise RegistryError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise RegistryError("配置根节点必须是 mapping")
    if data.get("schema") != "wr-sources/v1":
        raise RegistryError(f"schema 不匹配: {data.get('schema')!r} != 'wr-sources/v1'")
    return data


class Registry:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.tier_policy: dict[str, dict] = data.get("tier_policy", {})
        self.assertion_sets: dict[str, dict] = data.get("assertion_sets", {})
        self.routing: dict[str, dict] = data.get("content_routing", {})
        self.sources: dict[str, dict] = {}
        for item in data.get("sources", []):
            sid = item.get("id")
            if sid in self.sources:
                raise RegistryError(f"信源 id 重复: {sid}")
            self.sources[sid] = item

    # ------------------------------------------------------------------ #
    # 策略合成
    # ------------------------------------------------------------------ #
    def effective_policy(self, source_id: str) -> dict[str, Any]:
        """tier_policy 为默认值，source 级字段覆盖之（更严或同级）。"""
        src = self.sources.get(source_id)
        if src is None:
            raise RegistryError(f"未知信源: {source_id}")
        tier = src.get("tier")
        if tier not in self.tier_policy:
            raise RegistryError(f"信源 {source_id} 的 tier {tier!r} 未定义策略")
        policy = dict(self.tier_policy[tier])
        policy["tier"] = tier
        for key, value in src.items():
            if key in {"id", "name", "endpoint", "notes", "refresh_minutes",
                       "tier", "kind", "content_types", "assert", "fallback",
                       "verified", "license", "assertions_extra"}:
                continue
            policy[key] = value
        policy.setdefault("clue_only", False)
        policy.setdefault("requires_second_source",
                          self.tier_policy[tier].get("requires_second_source", False))
        policy["license"] = src.get("license", "public")
        return policy

    # ------------------------------------------------------------------ #
    # 路由
    # ------------------------------------------------------------------ #
    def route(self, content_type: str) -> dict[str, Any]:
        if content_type not in self.routing:
            raise RegistryError(
                f"未知内容类型: {content_type}；可选: {', '.join(sorted(self.routing))}"
            )
        cfg = self.routing[content_type]

        def pack(ids: list[str]) -> list[dict[str, Any]]:
            out = []
            for sid in ids:
                pol = self.effective_policy(sid)
                out.append({
                    "id": sid,
                    "name": self.sources[sid]["name"],
                    "tier": pol["tier"],
                    "license": pol["license"],
                    "redistribution": pol.get("redistribution"),
                    "cite_as_fact": pol.get("cite_as_fact", False),
                    "clue_only": pol.get("clue_only", False),
                    "allow_ai_paraphrase": pol.get("allow_ai_paraphrase", True),
                    "endpoint": self.sources[sid]["endpoint"],
                })
            return out

        return {
            "content_type": content_type,
            "label": cfg.get("label", content_type),
            "primary": pack(cfg.get("primary", [])),
            "secondary": pack(cfg.get("secondary", [])),
            "forbidden": list(cfg.get("forbidden", [])),
            "rules": cfg.get("rules", {}),
            "note": cfg.get("note", ""),
        }

    # ------------------------------------------------------------------ #
    # 字段级断言
    # ------------------------------------------------------------------ #
    def assert_record(self, source_id: str, record: dict[str, Any]) -> list[str]:
        """返回违规列表；空列表表示通过。抓取层解析后应立即调用。"""
        src = self.sources.get(source_id)
        if src is None:
            return [f"未知信源: {source_id}"]

        violations: list[str] = []
        set_names = src.get("assert") or []
        merged: dict[str, Any] = {}
        for name in set_names:
            spec = self.assertion_sets.get(name)
            if spec is None:
                violations.append(f"断言集不存在: {name}")
                continue
            for key, value in spec.items():
                if key == "not_null":
                    merged.setdefault("not_null", [])
                    merged["not_null"].extend(value)
                elif key in {"regex", "range"}:
                    merged.setdefault(key, {})
                    merged[key].update(value)

        extra = src.get("assertions_extra") or {}
        for key, value in extra.items():
            if key == "not_null":
                merged.setdefault("not_null", []).extend(value)
            else:
                merged.setdefault(key, {}).update(value)

        for field in merged.get("not_null", []):
            if field not in record or record[field] in (None, "", [], {}):
                violations.append(f"字段缺失或为空: {field}")

        for field, pattern in merged.get("regex", {}).items():
            value = record.get(field)
            if value is None:
                continue
            if not re.match(pattern, str(value)):
                violations.append(f"字段格式不符: {field}={value!r} 不匹配 {pattern}")

        for field, bounds in merged.get("range", {}).items():
            value = record.get(field)
            if value is None:
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                violations.append(f"字段非数值: {field}={value!r}")
                continue
            low, high = bounds
            if not (low <= num <= high):
                violations.append(f"字段越界: {field}={num} 不在 [{low}, {high}]")

        # L4 只做线索：任何 citation 字段都不允许被当成事实出处
        pol = self.effective_policy(source_id)
        if pol.get("clue_only") and record.get("used_as") == "fact":
            violations.append(f"{source_id} 为线索源，不得作为事实出处")

        return violations

    # ------------------------------------------------------------------ #
    # 授权检查
    # ------------------------------------------------------------------ #
    def check_license(self, source_id: str, usage: str = "internal") -> None:
        """usage: internal(内部研判) / public(对外发布) / client(付费客户)"""
        pol = self.effective_policy(source_id)
        license_ = pol.get("license")
        redistribution = pol.get("redistribution")

        if usage == "internal":
            return
        if license_ == "paid_internal" and usage in {"public", "client"}:
            raise RegistryError(
                f"{source_id}: license=paid_internal，禁止对外发布原始数据，只能引用结论"
            )
        if redistribution == "forbidden" and usage in {"public", "client"}:
            raise RegistryError(f"{source_id}: redistribution=forbidden，不得对外分发")

    # ------------------------------------------------------------------ #
    # 配置自检
    # ------------------------------------------------------------------ #
    def lint(self) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warns: list[str] = []
        unverified: list[str] = []

        for tier in VALID_TIERS:
            if tier not in self.tier_policy:
                errors.append(f"tier_policy 缺少 {tier}")

        for sid, src in self.sources.items():
            missing = REQUIRED_SOURCE_KEYS - set(src)
            if missing:
                errors.append(f"{sid}: 缺少必备字段 {sorted(missing)}")
            if src.get("tier") not in VALID_TIERS:
                errors.append(f"{sid}: 非法 tier {src.get('tier')!r}")
            cts = src.get("content_types") or []
            if not cts:
                errors.append(f"{sid}: content_types 为空")
            for ct in cts:
                if ct not in self.routing:
                    errors.append(f"{sid}: 引用了未定义的内容类型 {ct}")
            for name in (src.get("assert") or []):
                if name not in self.assertion_sets:
                    errors.append(f"{sid}: 断言集不存在 {name}")
            for fb in (src.get("fallback") or []):
                if fb not in self.sources:
                    errors.append(f"{sid}: fallback 指向未知信源 {fb}")
            if src.get("verified") is None:
                unverified.append(sid)
            if src.get("tier") == "L4":
                pol = self.effective_policy(sid)
                if pol.get("cite_as_fact"):
                    errors.append(f"{sid}: L4 信源不得 cite_as_fact=true")
                if not pol.get("clue_only"):
                    errors.append(f"{sid}: L4 信源必须 clue_only=true")

        for ct, cfg in self.routing.items():
            prim = cfg.get("primary") or []
            sec = cfg.get("secondary") or []
            forb = cfg.get("forbidden") or []
            clue_ok = bool(cfg.get("allow_clue_primary"))
            if not prim:
                errors.append(f"路由 {ct}: primary 为空")
            for sid in prim + sec:
                if sid not in self.sources:
                    errors.append(f"路由 {ct}: 引用未知信源 {sid}")
            for sid in forb:
                if sid not in self.sources:
                    errors.append(f"路由 {ct}: forbidden 引用未知信源 {sid}")
            overlap = set(prim) & set(forb)
            if overlap:
                errors.append(f"路由 {ct}: 同一信源同时出现在 primary 与 forbidden: {sorted(overlap)}")
            for sid in prim:
                if sid not in self.sources:
                    continue
                if self.sources[sid].get("tier") == "L4" and not clue_ok:
                    warns.append(f"路由 {ct}: 线索源 {sid} 出现在事实首位，请确认只作触发")
                try:
                    self.check_license(sid, usage="public")
                except RegistryError as exc:
                    warns.append(f"路由 {ct}: {exc}")

        if unverified:
            warns.append(
                f"{len(unverified)} 个信源尚未实测（verified=null），生产环境应禁用: "
                + ", ".join(unverified)
            )

        ap = self.data.get("pre_publish_assertions", {})
        if ap.get("enabled") and not ap.get("forbidden_phrases"):
            warns.append("pre_publish_assertions: 禁语库为空，等于没有禁语检查")
        if ap.get("enabled") and not ap.get("required_blocks"):
            warns.append("pre_publish_assertions: 必需段落未定义，免责声明无法自动校验")

        return errors, warns


# --------------------------------------------------------------------------- #
# 自测
# --------------------------------------------------------------------------- #
def selftest(reg: Registry) -> int:
    failures = 0

    good = {
        "doc_id": "2026-103", "title": "关于股东承诺事项的公告",
        "url": "https://www.cninfo.com.cn/new/disclosure/detail?x=1",
        "published_at": "2026-10-28 19:02",
    }
    v = reg.assert_record("cninfo", good)
    print(f"[{'PASS' if not v else 'FAIL'}] 合规公告记录 -> {v or '无违规'}")
    failures += bool(v)

    bad = {"doc_id": "2026-104", "title": "", "url": "ftp://x", "published_at": "昨天"}
    v = reg.assert_record("cninfo", bad)
    print(f"[{'PASS' if len(v) >= 3 else 'FAIL'}] 残缺公告记录 -> 捕获 {len(v)} 条: {v}")
    failures += not (len(v) >= 3)

    v = reg.assert_record("xueqiu", {"url": "https://xueqiu.com/1", "used_as": "fact"})
    hit = any("线索源" in item for item in v)
    print(f"[{'PASS' if hit else 'FAIL'}] L4 冒用为事实出处 -> {v}")
    failures += not hit

    try:
        reg.check_license("wind", usage="public")
        print("[FAIL] wind 对外发布应被拦截，但没有")
        failures += 1
    except RegistryError as exc:
        print(f"[PASS] wind 对外发布被拦截 -> {exc}")

    try:
        reg.check_license("wind", usage="internal")
        print("[PASS] wind 内部使用放行")
    except RegistryError as exc:
        print(f"[FAIL] wind 内部使用不应被拦截 -> {exc}")
        failures += 1

    r = reg.route("company_fact")
    ok = r["primary"] and all(s["cite_as_fact"] for s in r["primary"])
    print(f"[{'PASS' if ok else 'FAIL'}] company_fact 路由 -> "
          f"{[s['id'] for s in r['primary']]}")
    failures += not ok

    return failures


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="信源登记表工具")
    parser.add_argument("command", choices=["lint", "route", "policy", "selftest", "export-json"])
    parser.add_argument("target", nargs="?", help="content_type 或 source_id 或输出路径")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args(argv)

    reg = Registry(load(args.config))

    if args.command == "lint":
        errors, warns = reg.lint()
        for w in warns:
            print(f"WARN  {w}")
        for e in errors:
            print(f"ERROR {e}")
        print(f"\n结果: {len(errors)} error / {len(warns)} warn / {len(reg.sources)} sources")
        return 1 if errors else 0

    if args.command == "route":
        if not args.target:
            parser.error("route 需要 content_type 参数")
        print(json.dumps(reg.route(args.target), ensure_ascii=False, indent=2))
        return 0

    if args.command == "policy":
        if not args.target:
            parser.error("policy 需要 source_id 参数")
        print(json.dumps(reg.effective_policy(args.target), ensure_ascii=False, indent=2))
        return 0

    if args.command == "selftest":
        return 1 if selftest(reg) else 0

    if args.command == "export-json":
        out = Path(args.target or "routes.json")
        payload = {ct: reg.route(ct) for ct in reg.routing}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已导出 {len(payload)} 条路由 -> {out}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

