"""
HTML -> clean Markdown pipeline.

Stage A: Boilerplate removal (35+ selectors)
Stage B: HTML -> Markdown conversion (markdownify, GFM)
Stage C: Post-processing (whitespace cleanup, CJK adaptation)
"""
import re
from urllib.parse import urljoin
from typing import List, Optional


EXCLUDE_NON_MAIN_TAGS = [
    "header", "footer", "nav", "aside",
    ".header", ".top", ".navbar", "#header",
    ".footer", ".bottom", "#footer",
    ".sidebar", ".side", ".aside", "#sidebar",
    ".modal", ".popup", "#modal", ".overlay",
    ".ad", ".ads", ".advert", "#ad",
    ".lang-selector", ".language", "#language-selector",
    ".social", ".social-media", ".social-links", "#social",
    ".menu", ".navigation", "#nav",
    ".breadcrumbs", "#breadcrumbs",
    ".share", "#share",
    ".widget", "#widget",
    ".cookie", "#cookie",
]

GOV_EXCLUDE_TAGS = [
    ".gov-footer", ".gov-header", ".gov-nav", ".gov-sidebar",
    ".crumb", ".breadcrumb", ".location",
    ".pagination", ".page-nav", ".pager",
    ".print-btn", ".print-button",
    ".share-bar", ".share-box",
    ".toolbar", ".tools",
    ".related-links", ".related-news",
    ".copyright", ".icp",
    ".gov-search", ".search-box",
    ".user-info", ".login-bar",
    "script", "style", "noscript", "meta", "head",
]

FORCE_INCLUDE_TAGS = [
    "#main", "#content", "#article", "#body",
    ".main", ".content", ".article", ".body",
    ".article-content", ".news-content", ".detail-content",
    ".TRS_Editor", ".Custom_UnionStyle",
    "[role='main']", "[role='article']",
]

ALWAYS_REMOVE_TAGS = [
    "script", "style", "noscript", "meta", "head", "iframe",
    "link[rel='stylesheet']", "svg",
]


def clean_html(
    html: str,
    url: str = "",
    only_main_content: bool = True,
    extra_exclude: Optional[List[str]] = None,
    extra_include: Optional[List[str]] = None,
) -> str:
    """Stage A: HTML cleaning — remove boilerplate, absolutify URLs."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    for selector in ALWAYS_REMOVE_TAGS:
        for el in soup.select(selector):
            el.decompose()

    if only_main_content:
        exclude_list = list(EXCLUDE_NON_MAIN_TAGS) + GOV_EXCLUDE_TAGS
        if extra_exclude:
            exclude_list.extend(extra_exclude)
        include_list = list(FORCE_INCLUDE_TAGS)
        if extra_include:
            include_list.extend(extra_include)

        protected = set()
        for selector in include_list:
            for el in soup.select(selector):
                protected.add(id(el))
                parent = el.parent
                while parent is not None and hasattr(parent, 'name') and parent.name:
                    protected.add(id(parent))
                    parent = parent.parent

        for selector in exclude_list:
            for el in soup.select(selector):
                if id(el) not in protected:
                    el.decompose()

    if url:
        for el in soup.select("img[src]"):
            src = el.get("src", "")
            if src and not src.startswith(("http://", "https://", "data:")):
                el["src"] = urljoin(url, src)

        for el in soup.select("a[href]"):
            href = el.get("href", "")
            if href and not href.startswith(("http://", "https://", "javascript:", "#", "mailto:")):
                el["href"] = urljoin(url, href)

    return str(soup)


def html_to_markdown(
    html: str,
    url: str = "",
    heading_style: str = "ATX",
    only_main_content: bool = True,
) -> str:
    """HTML -> clean Markdown (full pipeline)."""
    cleaned = clean_html(html, url=url, only_main_content=only_main_content)

    try:
        from markdownify import markdownify as md_convert
        md = md_convert(
            cleaned,
            heading_style=heading_style,
            strip=["img"],
            newline_style="BACKSLASH",
            code_language_callback=lambda el: _detect_language(el),
        )
    except ImportError:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(cleaned, "lxml")
        md = soup.get_text(separator="\n", strip=True)

    md = _post_process(md)
    return md


def _post_process(md: str) -> str:
    md = re.sub(r'\[Skip to Content\]\(#[^\)]*\)', '', md, flags=re.IGNORECASE)
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = '\n'.join(line.strip() for line in md.split('\n'))
    md = re.sub(r'\n\s*\n', '\n\n', md)
    md = md.strip()
    return md


def _detect_language(el) -> str:
    classes = el.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    for cls in classes:
        cls_lower = cls.lower()
        if cls_lower in ("python", "javascript", "java", "sql", "bash", "json", "xml", "html", "css"):
            return cls_lower
        if cls_lower.startswith("language-"):
            return cls_lower[9:]
    return ""


def extract_title(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in ["h1", "h2"]:
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(strip=True)
    return ""


def extract_links(html: str, base_url: str = "") -> List[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    links = []
    seen = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        text = a.get_text(strip=True)
        if not href or not text:
            continue
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        full_url = urljoin(base_url, href) if base_url else href
        if full_url not in seen:
            seen.add(full_url)
            links.append({"url": full_url, "text": text[:200]})
    return links


def extract_tables_to_json(html: str) -> List[dict]:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    tables = []
    for table in soup.select("table"):
        rows = []
        for tr in table.select("tr"):
            cells = [cell.get_text(strip=True) for cell in tr.select("th, td")]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables
