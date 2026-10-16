#!/usr/bin/env python3
"""
Synchronize EOIC site files whenever new reports/{TICKER}.html and sources/{TICKER}_EOIC_{DATE}.md are added.
Automatically updates:
1. assets/search-index.js (window.EOIC_INDEX)
2. index.html (sidebar, filter counts, date groups, report cards)
3. reports/*.html (sidebar, filter counts, and prev/next footer links)
"""
from __future__ import annotations

import html as h
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

SITE_DIR = Path(__file__).resolve().parent

TAG_GROUPS_ORDER = [
    ("變現狀態", ["已變現", "未變現"], True),
    ("營運方向", ["修復", "加速", "擴張", "減速"], False),
    ("產業", ["半導體與硬體", "工業與設備", "消費與零售", "環境與公用事業", "軟體與雲端", "醫療與製藥", "金融"], False),
    ("創新主軸", ["人工智慧", "平台訂閱", "新產品", "自動化效率", "資料中心"], False),
    ("風險提醒", ["一次性收益", "仍在虧損", "併購干擾", "毛利下滑", "現金未跟上", "看外部環境"], False),
]


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

    return (
        f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="description" content="EOIC 企業營運與創新週期分析報告">'
        f'<title>EOIC automatic</title><link rel="stylesheet" href="assets/site.css"></head>'
        f'<body><a class="skip" href="#main">跳至內容</a>'
        f'<button class="mobile-bar" type="button" data-drawer-open aria-expanded="false" aria-controls="site-sidebar">'
        f'<strong>EOIC automatic</strong><span>清單</span></button>'
        f'<div class="drawer-mask" data-drawer-close hidden></div>'
        f'{sidebar_html}'
        f'<div class="page-content">'
        f'<header class="site-head"><h1>EOIC automatic</h1>'
        f'<p>搜尋 {total} 份企業營運與創新週期報告，快速掌握主要判斷與關鍵數字。</p></header>'
        f'<main id="main" class="index-main"><div id="report-list">{"".join(date_sections)}</div>'
        f'<section id="empty" class="empty" hidden><h2>沒有符合的報告</h2><button>清除條件</button></section></main>'
        f'<footer class="site-footer">公開閱讀 · 內容與數字依各份原稿原樣呈現</footer></div>'
        f'<script src="assets/search-index.js" defer></script>'
        f'<script src="assets/site.js" defer></script></body></html>'
    )


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

    # 2. Update index.html
    new_index_html = build_index_html(parsed, dates_ordered, by_date, tag_counts)
    index_path.write_text(new_index_html, encoding="utf-8")

    # 3. Update sidebar and footer in each reports/*.html
    for i, r in enumerate(parsed):
        rep_path = r["path"]
        rep_html = rep_path.read_text(encoding="utf-8")

        new_sidebar = build_sidebar(parsed, dates_ordered, by_date, tag_counts, is_report_page=True, current_code=r["code"])
        rep_html = re.sub(r'<aside id="site-sidebar" class="site-sidebar">.*?</aside>', lambda _: new_sidebar, rep_html, count=1, flags=re.S)

        prev_link = f'<a href="{esc(parsed[i - 1]["code"])}.html">← {esc(parsed[i - 1]["code"])}</a>' if i > 0 else "<span></span>"
        next_link = f'<a href="{esc(parsed[i + 1]["code"])}.html">{esc(parsed[i + 1]["code"])} →</a>' if i + 1 < len(parsed) else "<span></span>"
        new_footer = (
            f'<footer class="report-footer">'
            f'{prev_link}'
            f'<a href="../index.html">回首頁</a>'
            f'<a href="../{esc(r["source_rel"])}" download>下載完整分析稿</a>'
            f'{next_link}'
            f'</footer>'
        )
        rep_html = re.sub(r'<footer class="report-footer">.*?</footer>', lambda _: new_footer, rep_html, count=1, flags=re.S)
        rep_path.write_text(rep_html, encoding="utf-8")

    print(f"Synced {len(parsed)} reports across index.html, assets/search-index.js, and reports/*.html.")


if __name__ == "__main__":
    main()
