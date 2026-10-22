#!/usr/bin/env python3
"""
Synchronize EOIC site files whenever new reports/{TICKER}.html and sources/{TICKER}_EOIC_{DATE}.md are added.
Automatically updates:
1. assets/search-index.js (window.EOIC_INDEX)
2. feed.xml (RSS 2.0 feed)
3. index.html (sidebar, filter counts, date groups, report cards, and EOIC matrix view)
4. reports/*.html (sidebar, filter counts, breadcrumbs, related reports, OG tags, and prev/next footer links)
"""
from __future__ import annotations

import html as h
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SITE_DIR = Path(__file__).resolve().parent
BASE_URL = "https://joyce5438.github.io/eoic-automatic"

TAG_GROUPS_ORDER = [
    ("變現狀態", ["已變現", "未變現"], True),
    ("營運方向", ["修復", "加速", "擴張", "減速"], False),
    ("產業", ["半導體與硬體", "工業與設備", "消費與零售", "環境與公用事業", "軟體與雲端", "醫療與製藥", "金融"], False),
    ("創新主軸", ["人工智慧", "平台訂閱", "新產品", "自動化效率", "資料中心"], False),
    ("風險提醒", ["一次性收益", "仍在虧損", "併購干擾", "毛利下滑", "現金未跟上", "看外部環境"], False),
]

DIRECTIONS_ORDER = ["加速", "擴張", "修復", "減速"]


def esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def strip_tags(html_str: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html_str)
    return re.sub(r"\s+", " ", h.unescape(text)).strip()


def load_existing_index_cache(index_path: Path) -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    if not index_path.exists():
        return cache
    idx_html = index_path.read_text(encoding="utf-8")
    for card in re.findall(r'<article class="report-card".*?</article>', idx_html, re.S):
        code_m = re.search(r'data-code="([^"]+)"', card)
        comp_m = re.search(r'<strong class="ticker">[^<]+</strong><span>([^<]+)</span>', card)
        per_m = re.search(r'<footer class="card-footer"><span>([^<]*)</span>', card)
        if code_m:
            code = code_m.group(1)
            cache[code] = {
                "company": h.unescape(comp_m.group(1)) if comp_m else "",
                "period": h.unescape(per_m.group(1)) if per_m else "",
            }
    return cache


def infer_company_name(code: str, h1_text: str, prose_text: str, cached: str) -> str:
    if cached:
        return cached
    prefix = h1_text.split("｜")[0].strip()
    if prefix and prefix.upper() != code.upper():
        return prefix
    m = re.search(r"我將\s*([A-Za-z0-9 .&'-]+?)\s*的", prose_text)
    if m:
        return m.group(1).strip()
    return prefix or code


def infer_period(code: str, rep_html: str, prose_text: str, cached: str) -> str:
    if cached:
        return cached
    m = re.search(r"六季為\s*((?:FY)?\d{4}\s*Q[1-4])\s*(?:至|～|~|–|-)\s*((?:FY)?\d{4}\s*Q[1-4])", prose_text)
    if m:
        return f"{m.group(1)}–{m.group(2)}"
    sec_b = re.search(r'<h2 id="section-b">.*?<table>(.*?)</table>', rep_html, re.S)
    if sec_b:
        cells = re.findall(r"<tr><td[^>]*>(.*?)</td>", sec_b.group(1))
        if cells:
            last_cell = h.unescape(cells[-1]).split("／")[0].strip()
            m_short = re.match(r"^(FY)?(\d{2})Q([1-4])$", last_cell)
            if m_short:
                fy, yr, q = m_short.groups()
                return f"{fy or ''}20{yr} Q{q}"
            return last_cell
    return ""


def find_source_file(code: str, deadline_date: str) -> str:
    sources_dir = SITE_DIR / "sources"
    exact = sources_dir / f"{code}_EOIC_{deadline_date}.md"
    if exact.exists():
        return f"sources/{exact.name}"
    matches = sorted(sources_dir.glob(f"{code}_*.md"), reverse=True)
    if matches:
        return f"sources/{matches[0].name}"
    return f"sources/{code}_EOIC_{deadline_date}.md"


def parse_report(report_path: Path, cache: dict[str, dict[str, str]]) -> dict:
    rep_html = report_path.read_text(encoding="utf-8")
    code_m = re.search(r'<div class="eyebrow">([^<]+)</div>', rep_html)
    code = h.unescape(code_m.group(1)).strip() if code_m else report_path.stem

    h1_m = re.search(r"<h1>(.*?)</h1>", rep_html, re.S)
    h1_text = h.unescape(h1_m.group(1)).strip() if h1_m else f"{code}｜六季營運與創新週期"

    sub_m = re.search(r'<p class="subtitle">(.*?)</p>', rep_html, re.S)
    subtitle = h.unescape(sub_m.group(1)).strip() if sub_m else ""

    verdict_m = re.search(r'<aside class="hero-verdict"><span>[^<]*</span><strong>(.*?)</strong></aside>', rep_html, re.S)
    verdict = h.unescape(verdict_m.group(1)).strip() if verdict_m else ""

    date_m = re.search(r'<div class="deadline">資訊截止日\s*([^<]+)</div>', rep_html)
    date = h.unescape(date_m.group(1)).strip() if date_m else ""
    if not date:
        md_matches = sorted((SITE_DIR / "sources").glob(f"{code}_EOIC_*.md"), reverse=True)
        if md_matches:
            dm = re.search(r"(\d{4}-\d{2}-\d{2})", md_matches[0].name)
            if dm:
                date = dm.group(1)

    head_m = re.search(r'<header class="report-head">(.*?)</header>', rep_html, re.S)
    head_html = head_m.group(1) if head_m else rep_html
    tag_row_m = re.search(r'<div class="tag-row">(.*?)</div>\s*<div class="deadline">', head_html, re.S)
    tag_row_html = tag_row_m.group(1) if tag_row_m else ""

    tags_list: list[tuple[str, str, str]] = []
    for tm in re.finditer(r'<a class="([^"]+)"[^>]*data-tag="([^"]+)"\s+data-group="([^"]+)"[^>]*>', tag_row_html):
        cls, t_name, t_group = tm.groups()
        tags_list.append((h.unescape(t_name), h.unescape(t_group), cls))

    prose_m = re.search(r'<main id="main" class="prose">(.*?)</main>', rep_html, re.S)
    prose_html = prose_m.group(1) if prose_m else ""
    prose_plain = strip_tags(prose_html)

    cached_info = cache.get(code, {})
    company = infer_company_name(code, h1_text, prose_plain, cached_info.get("company", ""))
    period = infer_period(code, rep_html, prose_plain, cached_info.get("period", ""))

    sections = []
    parts = [p for p in re.split(r'(?=<h2 id="[^"]+">)', prose_html) if p.strip()]
    for part in parts:
        sm = re.match(r'<h2 id="([^"]+)">(.*?)</h2>(.*)', part, re.S)
        if sm:
            sid, h2_inner, sbody = sm.groups()
            sections.append({
                "id": sid,
                "title": strip_tags(h2_inner),
                "text": strip_tags(sbody),
            })

    tag_groups_dict: dict[str, list[str]] = {g_name: [] for g_name, _, _ in TAG_GROUPS_ORDER}
    for t_name, t_group, _ in tags_list:
        if t_group not in tag_groups_dict:
            tag_groups_dict[t_group] = []
        tag_groups_dict[t_group].append(t_name)

    source_rel = find_source_file(code, date)

    return {
        "path": report_path,
        "code": code,
        "company": company,
        "h1": h1_text,
        "subtitle": subtitle,
        "verdict": verdict,
        "date": date,
        "period": period,
        "tags": tags_list,
        "tag_groups": tag_groups_dict,
        "sections": sections,
        "source_rel": source_rel,
    }


def build_sidebar(
    reports: list[dict],
    dates_ordered: list[str],
    by_date: dict[str, list[dict]],
    tag_counts: dict[tuple[str, str], int],
    is_report_page: bool = False,
    current_code: str | None = None,
) -> str:
    total = len(reports)
    latest_date = dates_ordered[0] if dates_ordered else ""
    index_href = "../index.html" if is_report_page else "index.html"
    report_prefix = "../reports/" if is_report_page else "reports/"

    if is_report_page:
        search_html = (
            f'<form class="side-search" action="../index.html">'
            f'<label class="sr-only" for="report-search">搜尋全部報告</label>'
            f'<input id="report-search" name="q" type="search" placeholder="搜尋全部報告">'
            f'<button type="submit">搜尋</button></form>'
        )
    else:
        search_html = (
            f'<div class="side-search">'
            f'<label class="sr-only" for="search">搜尋報告</label>'
            f'<input id="search" type="search" placeholder="搜尋代號、公司、結論、標籤或全文" autocomplete="off">'
            f'<kbd>/</kbd></div>'
        )

    date_buttons = [f'<button class="filter-row date-filter active" data-date=""><span>全部</span><b>{total}</b></button>']
    for d in dates_ordered:
        date_buttons.append(
            f'<button class="filter-row date-filter" data-date="{esc(d)}"><span>{esc(d)}</span><b>{len(by_date[d])}</b></button>'
        )
    date_details = f'<details class="filter-group" open><summary>日期</summary><div class="filter-list">{"".join(date_buttons)}</div></details>'

    group_details = [date_details]
    for g_name, default_tags, is_open in TAG_GROUPS_ORDER:
        seen_tags = list(default_tags)
        for (tg, tt), cnt in sorted(tag_counts.items()):
            if tg == g_name and tt not in seen_tags and cnt > 0:
                seen_tags.append(tt)
        btns = []
        for t_name in seen_tags:
            cnt = tag_counts.get((g_name, t_name), 0)
            if cnt > 0 or t_name in default_tags:
                btns.append(
                    f'<button class="filter-row" data-tag="{esc(t_name)}" data-group="{esc(g_name)}">{esc(t_name)} <span>{cnt}</span></button>'
                )
        open_attr = " open" if is_open else ""
        group_details.append(
            f'<details class="filter-group" data-tag-group="{esc(g_name)}"{open_attr}><summary>{esc(g_name)}</summary><div class="filter-list">{"".join(btns)}</div></details>'
        )

    side_groups = []
    for d in dates_ordered:
        links = []
        for r in by_date[d]:
            cur_attr = ' aria-current="page"' if current_code == r["code"] else ""
            links.append(
                f'<a class="side-report-link" href="{report_prefix}{esc(r["code"])}.html" data-report-code="{esc(r["code"])}"{cur_attr}>'
                f'<strong>{esc(r["code"])}</strong><span>{esc(r["company"])}</span></a>'
            )
        side_groups.append(f'<section class="side-report-group" data-side-date="{esc(d)}"><h2>{esc(d)}</h2>{"".join(links)}</section>')

    return (
        f'<aside id="site-sidebar" class="site-sidebar">'
        f'<button class="drawer-close" type="button" data-drawer-close aria-label="關閉清單">關閉</button>'
        f'<header><a href="{index_href}">EOIC automatic</a><span>報告 {total} 份 · 最近更新 {esc(latest_date)}</span></header>'
        f'{search_html}'
        f'<section class="side-filters" aria-label="篩選報告">'
        f'{"".join(group_details)}'
        f'<div id="active-tags" class="active-tags"></div>'
        f'<div class="results"><strong id="result-count" aria-live="polite">找到 {total} 份</strong><button id="clear-all" hidden>清除條件</button></div>'
        f'</section>'
        f'<nav class="side-report-list" aria-label="報告清單">{"".join(side_groups)}</nav>'
        f'</aside>'
    )


def build_card(r: dict) -> str:
    tag_groups_json = json.dumps(r["tag_groups"], ensure_ascii=False, separators=(",", ":"))
    search_tokens = " ".join([
        r["code"].lower(),
        r["company"].lower(),
        r["h1"].lower(),
        r["subtitle"].lower(),
        r["verdict"].lower(),
        r["period"].lower(),
        " ".join(t[0].lower() for t in r["tags"]),
    ])

    visible_tags = r["tags"][:3]
    extra_count = len(r["tags"]) - len(visible_tags)
    tag_btns = []
    for t_name, t_group, cls in visible_tags:
        tag_btns.append(f'<button class="{esc(cls)}" data-tag="{esc(t_name)}" data-group="{esc(t_group)}">{esc(t_name)}</button>')
    if extra_count > 0:
        tag_btns.append(f'<span class="tag-more">+{extra_count}</span>')

    return (
        f'<article class="report-card" data-code="{esc(r["code"])}" data-date="{esc(r["date"])}" '
        f'data-tag-groups="{esc(tag_groups_json)}" data-search="{esc(search_tokens)}">'
        f'<div class="card-top"><strong class="ticker">{esc(r["code"])}</strong><span>{esc(r["company"])}</span></div>'
        f'<h3>{esc(r["subtitle"])}</h3>'
        f'<p class="verdict">{esc(r["verdict"])}</p>'
        f'<div class="tag-row">{"".join(tag_btns)}</div>'
        f'<div class="search-hits" hidden></div>'
        f'<footer class="card-footer"><span>{esc(r["period"])}</span>'
        f'<nav><a class="primary" href="reports/{esc(r["code"])}.html">開啟</a>'
        f'<a href="{esc(r["source_rel"])}" download>下載完整分析稿</a></nav></footer>'
        f'</article>'
    )


def build_matrix_html(reports: list[dict]) -> str:
    """Build the EOIC 2x2 / 4x2 Operating & Innovation Cycle Matrix View."""
    # Group reports by (status, direction)
    matrix_data: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in reports:
        status = r["tag_groups"].get("變現狀態", ["已變現"])[0]
        direction = r["tag_groups"].get("營運方向", ["修復"])[0]
        matrix_data[(status, direction)].append(r)

    def render_col(status_key: str, col_title: str, col_desc: str, col_cls: str) -> str:
        col_total = sum(len(matrix_data.get((status_key, d), [])) for d in DIRECTIONS_ORDER)
        quadrants = []
        for direction in DIRECTIONS_ORDER:
            items = matrix_data.get((status_key, direction), [])
            # Sort items alphabetically by ticker
            items_sorted = sorted(items, key=lambda x: x["code"])
            pills = []
            for item in items_sorted:
                tag_groups_json = json.dumps(item["tag_groups"], ensure_ascii=False, separators=(",", ":"))
                search_tokens = " ".join([
                    item["code"].lower(),
                    item["company"].lower(),
                    item["verdict"].lower(),
                    " ".join(t[0].lower() for t in item["tags"]),
                ])
                pills.append(
                    f'<a class="matrix-pill" href="reports/{esc(item["code"])}.html" '
                    f'data-code="{esc(item["code"])}" data-date="{esc(item["date"])}" '
                    f'data-tag-groups="{esc(tag_groups_json)}" data-search="{esc(search_tokens)}" '
                    f'title="{esc(item["company"])}｜{esc(item["verdict"])}">'
                    f'<strong>{esc(item["code"])}</strong>'
                    f'<span class="m-comp">{esc(item["company"])}</span>'
                    f'</a>'
                )
            pills_html = "".join(pills) if pills else '<span style="font-size:0.75rem;color:var(--weak);padding:0.4rem 0;">無標的</span>'
            quadrants.append(
                f'<div class="matrix-quadrant" data-status="{esc(status_key)}" data-direction="{esc(direction)}">'
                f'<div class="quadrant-title"><h4>{esc(direction)}</h4><span class="q-count">{len(items)} 份</span></div>'
                f'<div class="quadrant-pills">{pills_html}</div>'
                f'</div>'
            )
        return (
            f'<div class="matrix-column">'
            f'<header class="matrix-col-header {col_cls}">'
            f'<div><h3>{esc(col_title)}</h3><span style="font-size:0.75rem;color:var(--muted);">{esc(col_desc)}</span></div>'
            f'<span>{col_total} 份</span>'
            f'</header>'
            f'{"".join(quadrants)}'
            f'</div>'
        )

    col1 = render_col("已變現", "已變現（Monetized）", "創新已實質傳導至營收與利潤", "col-monetized")
    col2 = render_col("未變現", "未變現（Unmonetized）", "創新仍在研發投入或採用遲滯期", "col-unmonetized")

    return (
        f'<div id="matrix-view" class="matrix-view" hidden>'
        f'<div class="matrix-intro">'
        f'<div><strong>🧭 EOIC 營運與創新週期全景圖</strong>'
        f'<div style="margin-top:0.25rem;">橫軸檢視創新是否變現，縱軸檢視營運加速度；點選左側搜尋或標籤可同步動態高亮。</div></div>'
        f'<span style="font-size:0.75rem;color:var(--weak);">共 {len(reports)} 家公司</span>'
        f'</div>'
        f'<div class="matrix-columns">{col1}{col2}</div>'
        f'</div>'
    )


def build_feed_xml(reports: list[dict]) -> str:
    """Generate RSS 2.0 Feed for new reports."""
    items = []
    # Latest 35 reports
    for r in reports[:35]:
        link = f"{BASE_URL}/reports/{esc(r['code'])}.html"
        title = f"{esc(r['code'])}｜{esc(r['company'])} EOIC 報告"
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            pub_date = dt.strftime("%a, %d %b %Y 00:00:00 +0000")
        except Exception:
            pub_date = r["date"]
        desc = (
            f"【{esc(r['company'])} ({esc(r['code'])})】主要判斷：{esc(r['verdict'])}。"
            f"關鍵結論：{esc(r['subtitle'])}"
        )
        items.append(
            f"    <item>\n"
            f"      <title>{title}</title>\n"
            f"      <link>{link}</link>\n"
            f"      <guid isPermaLink=\"true\">{link}</guid>\n"
            f"      <pubDate>{pub_date}</pubDate>\n"
            f"      <description>{desc}</description>\n"
            f"    </item>"
        )
    items_str = "\n".join(items)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        f'  <channel>\n'
        f'    <title>EOIC automatic — 企業營運與創新週期分析</title>\n'
        f'    <link>{BASE_URL}/index.html</link>\n'
        f'    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        f'    <description>EOIC 企業營運與創新週期分析報告更新訂閱</description>\n'
        f'    <language>zh-Hant</language>\n'
        f'{items_str}\n'
        f'  </channel>\n'
        f'</rss>\n'
    )


def build_index_html(
    reports: list[dict],
    dates_ordered: list[str],
    by_date: dict[str, list[dict]],
    tag_counts: dict[tuple[str, str], int],
) -> str:
    total = len(reports)
    sidebar_html = build_sidebar(reports, dates_ordered, by_date, tag_counts, is_report_page=False)

    date_sections = []
    for d in dates_ordered:
        cards_html = "".join(build_card(r) for r in by_date[d])
        date_sections.append(
            f'<section class="date-group" data-date-group="{esc(d)}">'
            f'<header><h2>{esc(d)}</h2><span>{len(by_date[d])} 份</span></header>'
            f'<div class="card-grid">{cards_html}</div>'
            f'</section>'
        )

    matrix_html = build_matrix_html(reports)

    og_tags = (
        f'<meta property="og:type" content="website">\n'
        f'<meta property="og:title" content="EOIC automatic — 企業營運與創新週期分析報告">\n'
        f'<meta property="og:description" content="搜尋 {total} 份企業營運與創新週期報告，快速掌握主要判斷與關鍵財務數字。">\n'
        f'<meta property="og:url" content="{BASE_URL}/index.html">\n'
        f'<meta property="og:site_name" content="EOIC automatic">\n'
        f'<meta name="twitter:card" content="summary">\n'
        f'<meta name="twitter:title" content="EOIC automatic — 企業營運與創新週期分析">\n'
        f'<meta name="twitter:description" content="搜尋 {total} 份企業營運與創新週期報告，快速掌握主要判斷與關鍵財務數字。">\n'
        f'<link rel="alternate" type="application/rss+xml" title="EOIC automatic RSS Feed" href="feed.xml">'
    )

    return (
        f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f'<meta name="description" content="EOIC 企業營運與創新週期分析報告">\n'
        f'{og_tags}\n'
        f'<title>EOIC automatic</title><link rel="stylesheet" href="assets/site.css"></head>\n'
        f'<body><a class="skip" href="#main">跳至內容</a>\n'
        f'<button class="mobile-bar" type="button" data-drawer-open aria-expanded="false" aria-controls="site-sidebar">\n'
        f'<strong>EOIC automatic</strong><span>清單</span></button>\n'
        f'<div class="drawer-mask" data-drawer-close hidden></div>\n'
        f'{sidebar_html}\n'
        f'<div class="page-content">\n'
        f'<header class="site-head"><h1><a href="index.html">EOIC automatic</a></h1>\n'
        f'<p>搜尋 {total} 份企業營運與創新週期報告，快速掌握主要判斷與關鍵數字。</p></header>\n'
        f'<div class="view-switch" role="tablist" aria-label="檢視切換">\n'
        f'<button type="button" class="view-tab active" data-view="timeline" role="tab" aria-selected="true"><span>⏱️ 時間軸清單</span></button>\n'
        f'<button type="button" class="view-tab" data-view="matrix" role="tab" aria-selected="false"><span>🧭 週期全景矩陣</span></button>\n'
        f'</div>\n'
        f'<main id="main" class="index-main">\n'
        f'<div id="report-list">{"".join(date_sections)}</div>\n'
        f'{matrix_html}\n'
        f'<section id="empty" class="empty" hidden><h2>沒有符合的報告</h2><button>清除條件</button></section></main>\n'
        f'<footer class="site-footer"><span>公開閱讀 · 內容與數字依各份原稿原樣呈現</span> · <a href="feed.xml" target="_blank" style="color:var(--accent);text-decoration:none;">📡 訂閱 RSS Feed</a></footer></div>\n'
        f'<script src="assets/search-index.js" defer></script>\n'
        f'<script src="assets/site.js" defer></script></body></html>'
    )


REPORT_EXTRA_CSS = """
/* --- EOIC 6大功能升級樣式 --- */
.breadcrumb {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.78rem;
  color: var(--weak);
  margin-bottom: 0.85rem;
  flex-wrap: wrap;
}
.breadcrumb a {
  color: var(--muted);
  text-decoration: none;
}
.breadcrumb a:hover {
  color: var(--accent);
  text-decoration: underline;
}
.breadcrumb-sep {
  color: var(--card-line);
  font-size: 0.7rem;
}
.breadcrumb-current {
  color: var(--ink);
  font-weight: 700;
  font-family: ui-monospace, Consolas, monospace;
}
.table-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 1.5rem 0 0.4rem;
  padding: 0.45rem 0.6rem;
  background: var(--tag-bg);
  border: 1px solid var(--line);
  border-bottom: 0;
  border-radius: 6px 6px 0 0;
}
.table-scroll .table-tools + table {
  margin-top: 0;
}
.table-tools-badge {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--muted);
  letter-spacing: 0.04em;
}
.table-tools-btns {
  display: flex;
  gap: 0.5rem;
}
.btn-table-action {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.25rem 0.6rem;
  font-size: 0.72rem;
  font-weight: 600;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--paper);
  color: var(--ink);
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-table-action:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--bg);
}
.btn-table-action.copied {
  background: var(--monetized-bg);
  color: var(--monetized-ink);
  border-color: var(--monetized-ink);
}
.related-reports {
  max-width: 54rem;
  margin: 3.5rem auto 1.5rem;
  padding: 2rem 2rem 0;
  border-top: 2px solid var(--ink);
}
@media(max-width:600px) {
  .related-reports {
    padding-inline: 1.25rem;
  }
}
.related-head {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.related-head h3 {
  margin: 0;
  font-size: 1.15rem;
  font-weight: var(--cds-fw-heavy);
  letter-spacing: -0.02em;
}
.related-head .related-all-link {
  font-size: 0.78rem;
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}
.related-head .related-all-link:hover {
  text-decoration: underline;
}
.related-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 1rem;
}
.related-card {
  display: flex;
  flex-direction: column;
  padding: 1.1rem;
  background: var(--paper);
  border: 1px solid var(--card-line);
  border-radius: 8px;
  text-decoration: none;
  color: inherit;
  transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.related-card:hover {
  border-color: var(--accent);
  transform: translateY(-2px);
  box-shadow: 0 6px 18px -3px rgba(0,0,0,0.06);
}
.related-card-top {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.related-card-top strong {
  font-size: 1.2rem;
  font-weight: 800;
  font-family: ui-monospace, Consolas, monospace;
  color: var(--ink);
}
.related-card-top span.related-comp {
  font-size: 0.75rem;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.related-card-top .tag-dir {
  font-size: 0.65rem;
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
  background: var(--tag-bg);
  color: var(--tag-ink);
  font-weight: 600;
}
.related-card-verdict {
  margin: 0;
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--muted);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.report-footer {
  display: flex !important;
  justify-content: space-between;
  align-items: center;
  gap: 1.5rem;
  flex-wrap: wrap;
  max-width: 54rem;
  margin: 3rem auto 4rem;
  padding: 1.8rem 2rem 3.5rem;
  border-top: 1px solid var(--line);
  font-size: 0.85rem;
}
@media(max-width:600px) {
  .report-footer {
    padding-inline: 1.25rem;
    flex-direction: column;
    align-items: stretch;
    gap: 1rem;
    text-align: center;
  }
}
.report-footer-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 2rem; /* 寬裕舒適的間距 */
  flex-wrap: wrap;
}
.report-footer-nav a {
  color: var(--muted);
  text-decoration: none;
  padding: 0.4rem 0.8rem;
  border-radius: 5px;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.report-footer-nav a:hover {
  color: var(--accent);
  background: var(--tag-bg);
}
"""


def build_breadcrumb_html(r: dict) -> str:
    industry = r["tag_groups"].get("產業", ["全部報告"])[0] if r["tag_groups"].get("產業") else "全部報告"
    return (
        f'<nav class="breadcrumb" aria-label="導航路徑">'
        f'<a href="../index.html">首頁</a>'
        f'<span class="breadcrumb-sep">/</span>'
        f'<a href="../index.html#tag={quote(industry)}">{esc(industry)}</a>'
        f'<span class="breadcrumb-sep">/</span>'
        f'<span class="breadcrumb-current">{esc(r["code"])}</span>'
        f'</nav>'
    )


def build_related_html(r: dict, all_reports: list[dict]) -> str:
    """Find 2-3 peer reports in the same industry or direction."""
    industry = r["tag_groups"].get("產業", [""])[0] if r["tag_groups"].get("產業") else ""
    peers: list[dict] = []
    if industry:
        peers = [p for p in all_reports if p["code"] != r["code"] and industry in p["tag_groups"].get("產業", [])]

    # If fewer than 2 peers in the same industry, supplement with same direction
    if len(peers) < 2:
        direction = r["tag_groups"].get("營運方向", [""])[0] if r["tag_groups"].get("營運方向") else ""
        if direction:
            peers += [p for p in all_reports if p["code"] != r["code"] and p not in peers and direction in p["tag_groups"].get("營運方向", [])]

    selected_peers = peers[:3]
    if not selected_peers:
        return ""

    cards = []
    for peer in selected_peers:
        peer_dir = peer["tag_groups"].get("營運方向", [""])[0] if peer["tag_groups"].get("營運方向") else ""
        cards.append(
            f'<a class="related-card" href="{esc(peer["code"])}.html">'
            f'<div class="related-card-top">'
            f'<strong>{esc(peer["code"])}</strong>'
            f'<span class="related-comp">{esc(peer["company"])}</span>'
            f'<span class="tag-dir">{esc(peer_dir)}</span>'
            f'</div>'
            f'<p class="related-card-verdict">{esc(peer["verdict"])}</p>'
            f'</a>'
        )

    ind_label = f" · {esc(industry)}" if industry else ""
    tag_href = f'../index.html#tag={quote(industry)}' if industry else '../index.html'

    return (
        f'<section class="related-reports" aria-label="同賽道推薦">\n'
        f'<div class="related-head">\n'
        f'<h3>同賽道其他報告{ind_label}</h3>\n'
        f'<a class="related-all-link" href="{tag_href}">查看全部 →</a>\n'
        f'</div>\n'
        f'<div class="related-grid">{"".join(cards)}</div>\n'
        f'</section>\n'
    )


def update_report_html(
    rep_html: str,
    r: dict,
    all_reports: list[dict],
    prev_r: dict | None,
    next_r: dict | None,
    new_sidebar: str,
) -> str:
    """Inject Open Graph meta tags, breadcrumb, related reports, sidebar, and footer."""
    code = r["code"]
    company = r["company"]
    verdict = r["verdict"]
    subtitle = r["subtitle"]

    # 0. Inject or update REPORT_EXTRA_CSS inside <style>
    if "/* --- EOIC 6大功能升級樣式 --- */" in rep_html:
        rep_html = re.sub(
            r'/\* --- EOIC 6大功能升級樣式 --- \*/.*?(?=</style>)',
            REPORT_EXTRA_CSS.strip(),
            rep_html,
            flags=re.S
        )
    elif "</style>" in rep_html:
        rep_html = rep_html.replace("</style>", f"\n{REPORT_EXTRA_CSS.strip()}\n</style>", 1)

    # 1. Inject or update Open Graph / RSS in <head>
    og_meta = (
        f'<meta property="og:type" content="article">\n'
        f'<meta property="og:title" content="{esc(code)}｜{esc(company)} — 企業營運與創新週期 (EOIC)">\n'
        f'<meta property="og:description" content="{esc(verdict)}：{esc(subtitle)}">\n'
        f'<meta property="og:url" content="{BASE_URL}/reports/{esc(code)}.html">\n'
        f'<meta property="og:site_name" content="EOIC automatic">\n'
        f'<meta name="twitter:card" content="summary">\n'
        f'<meta name="twitter:title" content="{esc(code)}｜{esc(company)} — EOIC 報告">\n'
        f'<meta name="twitter:description" content="{esc(verdict)}">\n'
        f'<link rel="alternate" type="application/rss+xml" title="EOIC automatic RSS Feed" href="../feed.xml">\n'
        f'<link rel="stylesheet" href="../assets/site.css">'
    )

    # Clean existing og/twitter/rss/site.css if present
    rep_html = re.sub(r'<meta property="og:[^>]+>\n?', '', rep_html)
    rep_html = re.sub(r'<meta name="twitter:[^>]+>\n?', '', rep_html)
    rep_html = re.sub(r'<link rel="alternate"[^>]+>\n?', '', rep_html)
    rep_html = re.sub(r'<link rel="stylesheet" href="\.\./assets/site\.css">\n?', '', rep_html)

    # Insert after <title>
    rep_html = re.sub(r'(<title>.*?</title>)', r'\1\n' + og_meta, rep_html, count=1)

    # 2. Update sidebar
    rep_html = re.sub(r'<aside id="site-sidebar" class="site-sidebar">.*?</aside>', lambda _: new_sidebar, rep_html, count=1, flags=re.S)

    # 3. Inject Breadcrumb before <div class="eyebrow">
    breadcrumb_html = build_breadcrumb_html(r)
    if '<nav class="breadcrumb"' in rep_html:
        rep_html = re.sub(r'<nav class="breadcrumb"[^>]*>.*?</nav>', lambda _: breadcrumb_html, rep_html, count=1, flags=re.S)
    else:
        rep_html = re.sub(r'(<header class="report-head">)', r'\1' + breadcrumb_html, rep_html, count=1)

    # 4. Inject Related Reports before <footer class="report-footer">
    related_html = build_related_html(r, all_reports)
    if '<section class="related-reports"' in rep_html:
        rep_html = re.sub(r'<section class="related-reports"[^>]*>.*?</section>\n?', lambda _: related_html, rep_html, count=1, flags=re.S)
    else:
        rep_html = re.sub(r'(<footer class="report-footer">)', lambda m: related_html + m.group(1), rep_html, count=1)

    # 5. Update footer
    prev_link = f'<a href="{esc(prev_r["code"])}.html">← {esc(prev_r["code"])}</a>' if prev_r else "<span></span>"
    next_link = f'<a href="{esc(next_r["code"])}.html">{esc(next_r["code"])} →</a>' if next_r else "<span></span>"
    new_footer = (
        f'<footer class="report-footer">'
        f'{prev_link}'
        f'<div class="report-footer-nav">'
        f'<a href="../index.html">回首頁</a>'
        f'<a href="../feed.xml" target="_blank" style="display:inline-flex;align-items:center;gap:0.25rem;">📡 訂閱 RSS</a>'
        f'<a href="../{esc(r["source_rel"])}" download>下載完整分析稿</a>'
        f'</div>'
        f'{next_link}'
        f'</footer>'
    )
    rep_html = re.sub(r'<footer class="report-footer">.*?</footer>', lambda _: new_footer, rep_html, count=1, flags=re.S)

    return rep_html


def main() -> None:
    index_path = SITE_DIR / "index.html"
    cache = load_existing_index_cache(index_path)

    report_files = sorted((SITE_DIR / "reports").glob("*.html"))
    parsed = [parse_report(p, cache) for p in report_files]

    # Sort reports: date DESC, code DESC (matching existing site order)
    parsed.sort(key=lambda r: (r["date"], r["code"]), reverse=True)

    by_date: dict[str, list[dict]] = defaultdict(list)
    for r in parsed:
        by_date[r["date"]].append(r)
    dates_ordered = sorted(by_date.keys(), reverse=True)

    tag_counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in parsed:
        for t_name, t_group, _ in r["tags"]:
            tag_counts[(t_group, t_name)] += 1

    # 1. Update assets/search-index.js
    search_index_data = [
        {
            "code": r["code"],
            "company": r["company"],
            "date": r["date"],
            "url": f'reports/{r["code"]}.html',
            "sections": r["sections"],
        }
        for r in parsed
    ]
    search_index_str = "window.EOIC_INDEX = " + json.dumps(search_index_data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (SITE_DIR / "assets" / "search-index.js").write_text(search_index_str, encoding="utf-8")

    # 2. Update feed.xml (RSS 2.0)
    feed_xml_content = build_feed_xml(parsed)
    (SITE_DIR / "feed.xml").write_text(feed_xml_content, encoding="utf-8")

    # 3. Update index.html
    new_index_html = build_index_html(parsed, dates_ordered, by_date, tag_counts)
    index_path.write_text(new_index_html, encoding="utf-8")

    # 4. Update each reports/*.html
    for i, r in enumerate(parsed):
        rep_path = r["path"]
        rep_html = rep_path.read_text(encoding="utf-8")

        new_sidebar = build_sidebar(parsed, dates_ordered, by_date, tag_counts, is_report_page=True, current_code=r["code"])
        prev_r = parsed[i - 1] if i > 0 else None
        next_r = parsed[i + 1] if i + 1 < len(parsed) else None

        updated_html = update_report_html(rep_html, r, parsed, prev_r, next_r, new_sidebar)
        rep_path.write_text(updated_html, encoding="utf-8")

    print(f"Synced {len(parsed)} reports across index.html, feed.xml, assets/search-index.js, and reports/*.html.")


if __name__ == "__main__":
    main()
