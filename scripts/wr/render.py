"""渲染层：SVG 图表与静态页面。

页面结构与原版保持一致的视觉语言（同一套 CSS 变量与卡片式版式），
在此基础上增加：行情图表、数据截止提示、下周日历、上期判断回顾、AI 标识与完整免责。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import settings as S

ASSETS = Path(__file__).resolve().parent / "assets"


def _asset(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 图表


def svg_chart(metrics: dict) -> str:
    series = metrics.get("series") or {}
    dates, closes, turns = series.get("dates") or [], series.get("index") or [], series.get("turnover") or []
    if len(dates) < 2:
        return ""
    W, H = 920, 300
    L, R, T, B = 60, 64, 34, 44
    iw, ih = W - L - R, H - T - B
    t_max = max(turns) * 1.15
    c_lo, c_hi = min(closes), max(closes)
    span = (c_hi - c_lo) or max(c_hi * 0.002, 1.0)
    c_lo, c_hi = c_lo - span * 0.45, c_hi + span * 0.45
    n = len(dates)
    step = iw / n
    bw = min(40.0, step * 0.46)
    bits: list[str] = []
    for i in range(4):
        y = T + ih * i / 3
        bits.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - R}" y2="{y:.1f}" stroke="#ddd8cd" stroke-width="1"/>')
        bits.append(f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#8b8478">'
                    f'{t_max * (1 - i / 3) / 1e8:,.0f}</text>')
        bits.append(f'<text x="{W - R + 8}" y="{y + 4:.1f}" font-size="11" fill="#8b8478">'
                    f'{(c_hi - (c_hi - c_lo) * i / 3):,.0f}</text>')
    for idx, (day, turn) in enumerate(zip(dates, turns)):
        cx = L + step * (idx + 0.5)
        height = ih * (turn / t_max)
        bits.append(f'<rect x="{cx - bw / 2:.1f}" y="{T + ih - height:.1f}" width="{bw:.1f}" '
                    f'height="{height:.1f}" fill="#cdc6b8"/>')
        bits.append(f'<text x="{cx:.1f}" y="{H - 22}" text-anchor="middle" font-size="11" fill="#687078">'
                    f'{day[5:]}</text>')
    points = []
    for idx, close in enumerate(closes):
        cx = L + step * (idx + 0.5)
        cy = T + ih - ih * (close - c_lo) / (c_hi - c_lo)
        points.append(f"{cx:.1f},{cy:.1f}")
    bits.append('<polyline points="' + " ".join(points) + '" fill="none" stroke="#2c5d77" stroke-width="2.2"/>')
    for point in points:
        cx, cy = point.split(",")
        bits.append(f'<circle cx="{cx}" cy="{cy}" r="3.4" fill="#a52a35"/>')
    bits.append(f'<text x="{L}" y="16" font-size="11" fill="#687078">柱：主板成交额（亿港元，左轴）　'
                f'线：恒生指数收市（右轴，已截断）</text>')
    caption = (f"{metrics['first_session']} 至 {metrics['last_session']}，"
               f"周内高点 {S.fmt_index(metrics['high'])}（{metrics['high_date']}），"
               f"最新收市 {S.fmt_index(metrics['close'])}，"
               f"周涨跌 {S.fmt_pct(metrics['week_change_pct'])}。"
               f"右轴区间经截断以显示波动，柱状图纵轴自零起算。")
    return (f'<figure class="chart"><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="港股主板成交额与恒生指数 {metrics["first_session"]} 至 {metrics["last_session"]} 走势">'
            + "".join(bits) + f'</svg><figcaption class="chart-cap">{S.esc(caption)}</figcaption></figure>')


# ---------------------------------------------------------------- 引用


def cite(ids: list[str]) -> str:
    if not ids:
        return ""
    links = " ".join(f'<a href="#{S.esc(sid)}">{S.esc(sid)}</a>' for sid in dict.fromkeys(ids))
    return f'<sup class="cite">{links}</sup>'


def source_link(sid: str, item: dict) -> str:
    """来源标签直接链到原文，读到这里就能点开核对，不必再翻到页脚。"""
    label = S.esc(f'{sid} {item.get("source", "来源")}')
    url = str(item.get("url") or "").strip()
    if url.startswith(("http://", "https://")):
        return (f'<a href="{S.esc(url)}" target="_blank" rel="noopener noreferrer">'
                f'{label}<span class="ext">↗</span></a>')
    return label


def sid_link(sid: str, url: str) -> str:
    """同一来源多条时只写编号，每条各自可点开对应的原文。"""
    if url.startswith(("http://", "https://")):
        return (f'<a class="sid" href="{S.esc(url)}" target="_blank" rel="noopener noreferrer" '
                f'title="打开原文">{S.esc(sid)}</a>')
    return S.esc(sid)


def source_line(ids: list[str], sources: dict[str, dict], metric_ids: list[str] | None = None,
                basis: str = "") -> str:
    parts = []
    if ids:
        groups: dict[str, list[tuple[str, str]]] = {}
        for sid in dict.fromkeys(ids):
            item = sources.get(sid, {})
            name = str(item.get("source") or "来源")
            groups.setdefault(name, []).append((sid, str(item.get("url") or "").strip()))
        chunks = []
        for name, entries in groups.items():
            if len(entries) == 1:
                sid, url = entries[0]
                chunks.append(source_link(sid, {"source": name, "url": url}))
            elif len(entries) > 8:
                codes = "·".join(sid_link(sid, url) for sid, url in entries[:8])
                chunks.append(f'{S.esc(name)} {codes} 等 {len(entries)} 条'
                              '<a class="sid-more" href="#sources">完整列表 ↓</a>')
            else:
                codes = "·".join(sid_link(sid, url) for sid, url in entries)
                chunks.append(f"{S.esc(name)} {codes}")
        parts.append("来源：" + "，".join(chunks))
    if metric_ids:
        keys = [mid.removeprefix("m:") for mid in metric_ids]
        shown = "、".join(keys[:6])
        parts.append("计算：" + (shown + f" 等 {len(keys)} 项" if len(keys) > 6 else shown))
    if basis:
        parts.append(basis)
    return f'<p class="source">{"；".join(parts)}</p>' if parts else ""


def updates_lead(metrics: dict, others: list[dict]) -> str:
    """栏目导读：先说清这一栏是什么、覆盖多大范围、该怎么读。"""
    if not others:
        return ""
    cats = metrics.get("category_counts") or {}
    themes = metrics.get("themes") or {}
    total = int(metrics.get("issuers") or len(others))
    top_cat = max(cats.items(), key=lambda kv: kv[1])[0] if cats else ""
    top_themes = [name for name, _ in sorted(themes.items(), key=lambda kv: kv[1], reverse=True)[:3]]

    bits = [f"本期共 {total} 家标的披露公告，本栏归并为 {len(others)} 则"]
    if top_cat:
        bits.append(f"以{top_cat}为主")
    if top_themes:
        bits.append("覆盖" + "、".join(top_themes))
    return ("，".join(bits) +
            "。每条写两件事：这批披露透露了什么、该看什么；不逐条转述公告标题，"
            "报告期财务数值未解析，点条目末尾的来源即可打开原文核对。")


# ---------------------------------------------------------------- 页面


def render_report(report: dict, items: list[dict], period: dict, metrics: dict,
                  generated: dt.datetime, archive_url: str) -> str:
    sources = {item["id"]: item for item in items}
    stories = report.get("highlights", [])
    others = report.get("other_updates", [])
    watch = report.get("next_watch", [])
    previous = report.get("previous_check", [])
    chart = svg_chart(metrics) if S.cfg("render.chart", True) else ""

    market_cards = []
    for key, label in (("ashare", "A 股"), ("hk", "港股")):
        section = report[key]
        drivers = "".join(
            f'<li>{S.esc(driver["text"])}{cite(driver.get("source_ids", []))}</li>'
            for driver in section.get("drivers", [])
        )
        market_cards.append(
            f'<article class="market"><span class="tag">{label}</span><h3>{label}市场观察</h3>'
            f'<p>{S.esc(section.get("summary"))}{cite(section.get("summary_source_ids", []))}</p>'
            f'<ul>{drivers}</ul></article>'
        )

    story_html = []
    for story in stories:
        story_html.append(
            f'<article class="story"><p class="meta">{S.esc(story.get("market"))} · {S.esc(story.get("category"))}</p>'
            f'<h3>{S.esc(story.get("title"))}{cite(story.get("source_ids", []))}</h3>'
            f'<p class="reported"><b>发生了什么</b>{S.esc(story.get("reported"))}</p>'
            f'<div class="triple"><div class="analysis"><b>关注原因</b>{S.esc(story.get("analysis"))}</div>'
            f'<div class="watch"><b>下周验证</b>{S.esc(story.get("watch"))}</div></div>'
            f'{source_line(story.get("source_ids", []), sources, story.get("metric_ids"))}</article>'
        )

    update_html = []
    for story in others:
        update_html.append(
            f'<article class="update"><p class="meta">{S.esc(story.get("market"))} · {S.esc(story.get("category"))}</p>'
            f'<h3>{S.esc(story.get("title"))}{cite(story.get("source_ids", []))}</h3>'
            f'<p class="reading"><b>透露了什么</b>{S.esc(story.get("reported"))}</p>'
            + (f'<p class="takeaway"><b>小结</b>{S.esc(story.get("note"))}</p>'
               if str(story.get("note") or "").strip() else "")
            + f'{source_line(story.get("source_ids", []), sources)}</article>'
        )

    calendar_html = "".join(
        f'<li><span class="when">{S.esc(item.get("when") or item.get("text", ""))}</span>'
        f'<span class="what">{S.esc(item.get("name") or "")}</span>'
        f'<span class="tag-certainty">{S.esc(item.get("certainty") or "规则来源待补")}</span></li>'
        for item in watch
    )
    previous_html = "".join(
        f'<li><span class="status status-{S.esc(row["status"])}">{S.esc(row["status"])}</span>'
        f'{S.esc(row.get("title", ""))}　<span class="note">{S.esc(row.get("note", ""))}</span></li>'
        for row in previous
    )

    cited = _cited_ids(report)
    cited_rows, other_rows = [], []
    for item in items:
        if item.get("date_only"):
            stamp = item["published"].strftime("%Y-%m-%d") + "（仅日期）"
        else:
            stamp = item["published"].strftime("%Y-%m-%d %H:%M") + "（北京时间）"
        row = (f'<li id="{S.esc(item["id"])}"><b>[{S.esc(item["id"])}] {S.esc(item["market"])} · '
               f'{S.esc(item["source"])} · {S.esc(item["source_tier_label"])}</b>'
               f'<br><a href="{S.esc(item["url"])}" target="_blank" rel="noopener noreferrer">'
               f'{S.esc(item["title"])} ↗</a><br><small>{S.esc(stamp)} · '
               f'{S.esc(item.get("snippet", "")[:300])}</small></li>')
        (cited_rows if item["id"] in cited else other_rows).append(row)

    cutoff = metrics.get("data_through")
    cutoff_note = ""
    if cutoff and cutoff < period["end"].date().isoformat():
        cutoff_note = (f'<div class="datacut"><b>数据截止</b>　行情数据截至 {cutoff} 收市；'
                       f'统计区间截至 {period["end"]:%Y-%m-%d %H:%M} 的其余信息见下方来源。</div>')

    disclaimers = "".join(f"<li>{S.esc(line)}</li>" for line in S.cfg("compliance.disclaimers", []))
    ai_label = S.cfg("compliance.ai_label", "")
    start_txt = period["start"].strftime("%Y-%m-%d %H:%M")
    end_txt = period["end"].strftime("%Y-%m-%d %H:%M")
    generated_txt = generated.strftime("%Y-%m-%d %H:%M")
    facts = (
        f'<span><b>期号</b> {S.esc(period["edition"])}</span>'
        f'<span><b>统计区间</b> {start_txt} — {end_txt}</span>'
        + (f'<span><b>行情截至</b> {S.esc(cutoff)} 收市</span>' if cutoff else "")
        + ('<span><b>期次状态</b> 周内运行（区间截至生成时刻）</span>' if period.get("partial") else "")
        + '<span><b>时区</b> 北京时间</span>'
          f'<span><b>一手来源</b> {len(items)} 条</span>'
          f'<span><b>生成时间</b> {generated_txt}</span>'
    )

    nav = [
        ('#overview', '本期关注', True),
        ('#markets', '市场概览', True),
        ('#highlights', f'本周重点 · {len(stories)} 则', bool(stories)),
        ('#more', f'其他动态 · {len(others)} 则', bool(others)),
        ('#outlook', '下周日历', bool(watch)),
        ('#previous', '上期判断', bool(previous)),
        ('#sources', '来源与说明', True),
        (archive_url, '历史周报 ↗', True),
    ]
    nav_html = "".join(f'<a href="{href}">{S.esc(label)}</a>' for href, label, show in nav if show)

    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{S.esc(report.get('overview'))}">
<meta name="generator" content="ai-market-weekly {S.esc(period['edition'])}">
<title>{S.esc(report.get('headline'))}｜A/H AI 市场周报</title>
<style>
{_asset('site.css')}
{_asset('site-extra.css')}
</style></head><body><main class="wrap">
<header class="hero"><div class="eyebrow">A/H EQUITY · AI &amp; INNOVATION</div>
<h1>{S.esc(report.get("headline"))}</h1><p>A 股 / 港股 · 人工智能与科技创新市场观察</p></header>
<div class="facts">{facts}</div>
{cutoff_note}
<div class="layout"><aside class="rail"><strong>CONTENTS / 栏目</strong>{nav_html}</aside><div class="content">
<section id="overview"><h2>本期关注</h2><p class="lead">{S.esc(report.get("overview"))}</p>
{source_line(report.get("overview_source_ids", []), sources, report.get("overview_metric_ids"))}</section>
<section id="markets" class="section"><h2>市场概览</h2><div class="market-grid">{"".join(market_cards)}</div>{chart}</section>
<section id="highlights" class="section"><div class="section-heading"><h2>本周重点 · {len(story_html)} 则</h2>
<div class="export-actions"{"" if story_html else " hidden"}><button class="export-button" type="button" data-export-highlights>下载本周重点长图</button><span class="export-status" data-export-status aria-live="polite"></span></div></div>
{"".join(story_html) if story_html else '<p class="note">本期未能形成通过校验的判断条目。</p>'}</section>
{f'<section id="more" class="section"><h2>其他动态 · {len(update_html)} 则</h2><p class="note">{updates_lead(metrics, others)}</p>{"".join(update_html)}</section>' if update_html else ''}
{f'<section id="outlook" class="section"><h2>下周日历</h2><ul class="calendar">{calendar_html}</ul><p class="note">「规则推算」依据历史发布惯例估算，「法定截止日」为监管规定，「已登记」为人工维护事项。</p></section>' if calendar_html else ''}
{f'<section id="previous" class="section"><h2>上期判断</h2><ul class="prev-check">{previous_html}</ul><p class="note">「待验证」表示本期未取得足以判定的新证据，不代表判断成立。</p></section>' if previous_html else ''}
<section id="sources" class="section"><h2>来源与说明</h2>
<p class="note">本页所有事实性陈述均可回溯至下列一手来源；派生指标（涨跌幅、振幅、环比等）由程序按来源数据计算，计算口径见每条依据说明。</p>
<details class="source-details"><summary>报告引用来源（{len(cited_rows)} 条）</summary><ol class="sources">{"".join(cited_rows) or "<li>暂无引用来源。</li>"}</ol></details>
<details class="source-details"><summary>未引用采集线索（{len(other_rows)} 条）</summary><ol class="sources">{"".join(other_rows) or "<li>本期采集到的线索均已引用或未产生合格线索。</li>"}</ol></details></section>
<div class="disclaimer"><p><span class="badge-ai">AI 参与生成</span>{S.esc(ai_label)}</p><ol>{disclaimers}</ol></div>
</div></div></main><script>{_asset('export.js')}</script></body></html>'''


def _cited_ids(report: dict) -> set[str]:
    ids = set(report.get("overview_source_ids", []) or [])
    for key in ("ashare", "hk"):
        section = report.get(key, {})
        ids.update(section.get("summary_source_ids", []) or [])
        for driver in section.get("drivers", []) or []:
            ids.update(driver.get("source_ids", []) or [])
    for group in ("highlights", "other_updates", "next_watch", "previous_check"):
        for item in report.get(group, []) or []:
            ids.update(item.get("source_ids", []) or [])
    return ids


def render_archive(entries: list[dict]) -> str:
    rows = []
    for entry in entries:
        edition = entry.get("edition") or entry.get("date")
        badge = f'<span class="tag-certainty">{S.esc(entry.get("week_label", ""))}</span>' if entry.get("week_label") else ""
        rows.append(
            f'<article class="entry"><p class="meta">{S.esc(entry.get("period", ""))} · 北京时间 {badge}</p>'
            f'<h2><a href="{S.esc(edition)}.html">{S.esc(entry.get("label") or entry.get("date", ""))}｜{S.esc(entry.get("headline", ""))} ↗</a></h2>'
            f'<p>{S.esc(entry.get("overview", ""))}</p></article>'
        )
    if not rows:
        rows = ['<p class="empty">周报将在下一次 workflow 运行后生成。</p>']
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>A/H AI 市场周报｜历史目录</title>
<style>{_asset('archive.css')}</style></head><body><main class="wrap">
<header class="hero"><div class="eyebrow">A/H EQUITY · AI &amp; INNOVATION</div><h1>历史周报</h1>
<p>按期回看 A 股与港股科技创新、人工智能及市场动态。</p></header>
<a class="back" href="../">← 返回最新周报</a>
<section class="section"><h2>已发布期次</h2>{"".join(rows)}</section>
<footer>内容由程序与大模型协作整理，数字均经来源或计算核对；不构成投资建议。</footer></main></body></html>'''
