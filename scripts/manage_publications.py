from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from wr.render import render_archive  # noqa: E402


def delete_publication(publish_date: str) -> None:
    try:
        dt.date.fromisoformat(publish_date)
    except ValueError as exc:
        raise SystemExit("日期必须使用 YYYY-MM-DD 格式") from exc
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publish_date):
        raise SystemExit("日期必须使用 YYYY-MM-DD 格式")

    archive_path = ROOT / "data" / "archives.json"
    entries = json.loads(archive_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or not entries:
        raise SystemExit("历史目录为空，未执行删除")

    matches = [
        entry for entry in entries
        if (entry.get("publish_date") or str(entry.get("sort_value") or "")[:10]) == publish_date
    ]
    if len(matches) != 1:
        raise SystemExit(f"发布日期 {publish_date} 匹配到 {len(matches)} 条记录；必须唯一匹配")

    target = matches[0]
    edition = str(target.get("edition") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", edition):
        raise SystemExit("目标记录期次格式异常，拒绝删除")

    latest = max(
        entries,
        key=lambda entry: str(entry.get("sort_value") or entry.get("publish_date") or ""),
    )
    if target is latest:
        raise SystemExit("不能通过归档管理流程删除最新一期；请先发布新一期")

    report_html = ROOT / "weekly" / f"{edition}.html"
    report_json = ROOT / "weekly" / f"{edition}.json"
    missing = [str(path.relative_to(ROOT)) for path in (report_html, report_json) if not path.is_file()]
    if missing:
        raise SystemExit(f"报告文件不完整，拒绝修改归档：{', '.join(missing)}")

    report_html.unlink()
    report_json.unlink()
    remaining = [entry for entry in entries if entry is not target]
    remaining.sort(
        key=lambda entry: str(entry.get("sort_value") or entry.get("publish_date") or ""),
        reverse=True,
    )
    archive_path.write_text(json.dumps(remaining, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "weekly" / "index.html").write_text(render_archive(remaining), encoding="utf-8")
    print(f"Deleted {publish_date} ({edition}) and rebuilt archive index.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage published weekly reports")
    parser.add_argument("--delete-date", required=True, help="发布日期，格式 YYYY-MM-DD")
    args = parser.parse_args()
    delete_publication(args.delete_date)


if __name__ == "__main__":
    main()
