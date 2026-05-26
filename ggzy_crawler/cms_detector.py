"""CMS auto-detection: 15 CMS signatures + auto-derived configuration.

Rule-driven CMS detection for Chinese government procurement platforms.
Detects: epoint, TRS, huilan, generic_gov, cmstop, asp_net, java_cms,
query_param, content_pattern, api_json, tax_portal, and variants.
"""
import re
import json
from urllib.parse import urlparse, urljoin


# ── CMS Signature Library ────────────────────────────────────

CMS_SIGNATURES = [
    {
        "name": "epoint",
        "label": "Epoint (国泰新点)",
        "checks": {
            "ext_jhtml": (r'\.jhtml["\')\s>]', 8),
            "path_jyxx": (r'/jyxx/', 6),
            "meta_epoint": (r'epoint|国泰新点|Epoint', 2),
            "index_jhtml": (r'/jyxx/index\.jhtml', 3),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template": "/jyxx/index_{page}.jhtml",
                "url_template_first": "/jyxx/index.jhtml",
                "item_selector": "a[href*='.jhtml'], a[href*='.html']",
                "next_page_selector": "a:contains('下一页')",
                "max_pages": 200,
                "filter_href_include": r"((/jyxx/\d+/[a-f0-9\-]+\.(jhtml|html))|(/col\d*/art/\d+/art_[a-f0-9]+\.html)|(/[a-z]+/(\d{4,})\.jhtml))",
                "filter_href_exclude": ["index.jhtml", "index.html", "/zwgk/", "/jgxx/", "/xyxx/", "search.", "/fwzn/", "/zcfg/", "/xzzx/"],
            },
            "detail": {
                "title_selector": "h4 strong::text",
                "content_selector": ".div-article2 *::text",
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "trs",
        "label": "TRS WCM",
        "checks": {
            "col_pattern": (r'/col/col\d+/', 9),
            "art_trs": (r'/art/\d{4}/\d{1,2}/\d{1,2}/art_[a-f0-9_]+\.html', 8),
            "trs_editor": (r'TRS_Editor|TRS_PreAppend', 4),
            "meta_trs": (r'TRS|WCM', 1),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template": "/col/{col_id}/index_{page}.html",
                "url_template_first": "/col/{col_id}/index.html",
                "item_selector": "a[href*='/art/']",
                "next_page_selector": "a:contains('下一页'), a:contains('下页')",
                "max_pages": 1,
                "filter_href_include": r"(?:/col\w*)?/art/\d{4}/(?:\d{1,2}/){0,2}art_[a-f0-9_]+\.html",
                "filter_href_exclude": ["index.html", "index.htm", "javascript"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": ".TRS_Editor *::text, .TRS_PreAppend *::text, body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "huilan",
        "label": "Huilan (慧蓝)",
        "checks": {
            "ext_shtml": (r'\.shtml["\')\s>]', 8),
            "c_pattern": (r'/c\d+/\d+/[a-f0-9]+\.s?html', 6),
            "cms_html": (r'/cms/html/', 4),
            "meta_huilan": (r'huilan|慧蓝|Hanweb', 2),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.shtml'], a[href*='.html'], a[href*='/jyxx/']",
                "max_pages": 1,
                "filter_href_include": r"((art_|t)\d+|/c\d+/\d+/[a-f0-9]+|/\d{8}/[a-f0-9\-]+)\.(s?html|jhtml)",
                "filter_href_exclude": ["index", "javascript", "about", "list", "nav_"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "generic_gov",
        "label": "Generic Gov CMS (t_date/TRS/Java)",
        "checks": {
            "domain_gov": (r'\.gov\.cn', 5),
            "path_gsgg": (r'/gsgg/', 4),
            "path_tzgg": (r'/tzgg/', 3),
            "path_xxgk": (r'/xxgk/|/zwgk/', 3),
            "art_info": (r'/(?:art|info)/\d+', 5),
            "t_date": (r't\d{8}_\d+\.(?:html|htm|shtml)', 5),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='/art/'], a[href*='/info/'], a[href*='t202'], "
                                 "a[href$='.shtml'], a[href$='.html'], a[href*='/content/'], "
                                 "a[href*='/zwgk/'], a[href*='/tzgg/'], a[href*='/gsgg/'], "
                                 "a[href*='/gkxx/'], a[href*='/xxgk/']",
                "max_pages": 1,
                "filter_href_exclude": ["index.shtml", "index.html", "index.htm",
                                        "list.shtml", "list.html", "list.htm",
                                        "javascript", "nav_", "foot_", "header"],
            },
            "detail": {
                "fields": [
                    {"name": "page_title", "selector": "title::text"},
                    {"name": "content_text", "selector": (
                        ".TRS_Editor *::text, #content *::text, .article-content *::text, "
                        ".article_content *::text, .xqy-xl-room *::text, "
                        ".info-content *::text, .main-content *::text, body *::text"
                    )},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 20},
        },
    },
    {
        "name": "simple_html",
        "label": "Simple HTML",
        "checks": {
            "path_jyxx_simple": (r'/jyxx/\d+/\d+/\d{8}/[a-f0-9\-]+\.html', 8),
            "path_tzgg_date": (r'/tzgg/\d{8}/[a-f0-9\-]+\.html', 6),
            "ext_shtml": (r'\.shtml["\')\s>]', -2),
            "ext_jhtml": (r'\.jhtml["\')\s>]', -2),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.html'], a[href*='/jyxx/'], a[href*='/tzgg/']",
                "max_pages": 1,
                "filter_href_include": r"/jyxx/\d+/\d+/\d{8}/[a-f0-9\-]+\.html",
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "cmstop",
        "label": "CmsTop CMS",
        "checks": {
            "t_date_pattern": (r't\d{8}_\d+\.(?:shtml|html)', 9),
            "cmstop_meta": (r'cmstop|CmsTop', 3),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.shtml'], a[href*='.html']",
                "max_pages": 1,
                "filter_href_include": r"t\d{8}_\d+\.(?:shtml|html)",
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "asp_net",
        "label": "ASP.NET",
        "checks": {
            "ext_aspx": (r'\.aspx["\')\s>]', 9),
            "viewstate": (r'__VIEWSTATE|__EVENTVALIDATION', 5),
            "asp_portal": (r'PortalQD|NoticeList', 4),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.aspx'], a[href*='NoticeInfo']",
                "max_pages": 1,
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "java_cms",
        "label": "Java CMS (jsp/do)",
        "checks": {
            "ext_jsp": (r'\.jsp["\')\s>]', 8),
            "ext_do": (r'\.do["\')\s>]', 7),
            "news_detail": (r'NewsDetail|newsdetail', 3),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.jsp'], a[href*='.do'], a[href*='.html']",
                "max_pages": 1,
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "query_param",
        "label": "Query-param type",
        "checks": {
            "notice_info": (r'NoticeInfo\?|Detail\?|detail\?', 6),
            "query_id": (r'[?&](?:id|infoid|ItemId|articleid)=', 5),
            "no_html_links": (r'\.html["\')\s>]', -3),
            "no_shtml_links": (r'\.shtml["\')\s>]', -3),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='?']",
                "max_pages": 1,
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "content_pattern",
        "label": "content_NUM type",
        "checks": {
            "content_num": (r'content[_-]?\d+\.(?:html|shtml)', 8),
            "cms_content": (r'/content/\d+', 4),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='content_'], a[href*='/content/']",
                "max_pages": 1,
                "filter_href_include": r"content[_-]?\d+\.(?:html|shtml|htm)",
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "epoint_variant",
        "label": "Epoint variant (deep jyxx)",
        "checks": {
            "jyxx_deep": (r'/jyxx/\d{6}/\d{6}\w*/\d{8}/[a-f0-9\-]+\.html', 9),
            "jyxx_mid": (r'/jyxx/\d+/\d+/\d{8}/[a-f0-9\-]+\.html', 7),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='/jyxx/'], a[href*='.html']",
                "max_pages": 1,
                "filter_href_include": r"/jyxx/\d{6}/\d{6}\w*/\d{8}/[a-f0-9\-]+\.html",
                "filter_href_exclude": ["index", "javascript", "about", "list", "trade_info"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "huilan_hnsggzy",
        "label": "Hunan Huilan (hnsggzy)",
        "checks": {
            "hnsggzy_domain": (r'hnsggzy\.com', 7),
            "jyxx_path": (r'/jyxx/', 3),
        },
        "config": {
            "engine": "list_pagination_browser",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='/jyxx/'], a[href*='.shtml'], a[href*='.html']",
                "max_pages": 1,
                "filter_href_include": r"/jyxx/\d+/\d+/\d+/[a-f0-9\-]+\.html",
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "epoint_browser",
        "label": "Epoint JS-rendered (browser)",
        "checks": {
            "epoint_spa": (r'vue|react|webpack|chunk', 3),
            "spa_index": (r'<div\s+id=["\']app["\']', 4),
            "ext_jhtml": (r'\.jhtml["\')\s>]', 4),
        },
        "config": {
            "engine": "list_pagination_browser",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='.jhtml'], a[href*='.html']",
                "max_pages": 1,
                "filter_href_include": r"/jyxx/\d+/\d{8}/[a-f0-9\-]+\.html",
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
    {
        "name": "api_json",
        "label": "API JSON-driven",
        "checks": {
            "small_page": (r'^.{0,800}$', 3),
            "json_api_hint": (r'/api/|/front/|json|pageIndex|pageSize', 2),
        },
        "config": {
            "engine": "api_json",
            "list": {
                "url_template_first": "/",
                "max_pages": 1,
            },
            "api": {
                "url_template": "/front/bidcontent",
                "method": "POST",
                "content_type": "application/json",
                "body_template": {"pageIndex": "{page}", "pageSize": 15},
                "items_path": "rows",
                "text_field": "title",
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.0, "timeout": 30},
        },
    },
    {
        "name": "tax_portal",
        "label": "Tax Portal",
        "checks": {
            "tax_domain": (r'/tax|/shuiwu|/swj', 6),
        },
        "config": {
            "engine": "list_pagination",
            "list": {
                "url_template_first": "/",
                "item_selector": "a[href*='/art/'], a[href*='t202']",
                "max_pages": 1,
                "filter_href_exclude": ["index", "javascript", "about", "list"],
            },
            "detail": {
                "fields": [
                    {"name": "title", "selector": "title::text"},
                    {"name": "content_text", "selector": "body *::text"},
                ],
            },
            "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
        },
    },
]


def _score_cms(html, url):
    """Score each CMS signature against the HTML/URL. Returns [(name, score), ...]."""
    scores = []
    for sig in CMS_SIGNATURES:
        score = 0
        for key, (pattern, weight) in sig["checks"].items():
            if re.search(pattern, html, re.IGNORECASE):
                score += weight
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if any(kw in hostname for kw in ("tax", "shuiwu", "swj")):
            score += 5 if sig["name"] == "tax_portal" else 0
        if hostname.endswith((".cn", ".com.cn", ".org.cn", ".net.cn")):
            score += 2 if sig["name"] == "generic_gov" else 0
        scores.append((sig["name"], score))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores


def _derive_patterns(html, url):
    """Auto-derive best item_selector and filter_href_include from HTML links."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"

    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    hrefs = [h for h in hrefs if h and not h.startswith('#') and not h.startswith('javascript:')
             and not re.search(r'\.(css|js|png|jpg|gif|ico|svg|woff|ttf|eot|xml|rss|atom)(\?|$)', h, re.IGNORECASE)]

    patterns = {}
    for h in hrefs:
        p = h
        if p.startswith('http'):
            try:
                p = urlparse(p).path
            except Exception:
                continue
        for pat, regex in [
            ("art_date", r'/art/\d{4}/\d{1,2}/\d{1,2}/art_[a-f0-9_]+\.html'),
            ("jyxx_deep4", r'/jyxx/(?:\d+/){3,}\d{8}/[a-f0-9\-]+\.html'),
            ("jyxx_deep", r'/jyxx/(?:\d+/){2}\d{8}/[a-f0-9\-]+\.html'),
            ("jyxx_mid", r'/jyxx/\d+/\d+/\d{8}/[a-f0-9\-]+\.html'),
            ("t_date", r't\d{8}_\d+\.(?:s?html|htm)'),
            ("info_num", r'/info/\d+/\d+\.htm'),
            ("content_num", r'content[_-]?\d+\.(?:html|shtml)'),
            ("col_art", r'/col\d+/art/\d+/art_[a-f0-9]+\.html'),
            ("jhtml", r'\.jhtml'),
            ("shtml", r'\.shtml'),
            ("aspx", r'\.aspx'),
            ("jsp", r'\.jsp'),
            ("do_action", r'\.do\b'),
            ("query_detail", r'[?&](?:id|infoid|ItemId)=[a-f0-9\-]+'),
        ]:
            if re.search(regex, p, re.IGNORECASE):
                patterns[pat] = patterns.get(pat, 0) + 1

    if not patterns:
        return None, None

    best = max(patterns, key=patterns.get)

    filter_map = {
        "art_date": r"/art/\d{4}/\d{1,2}/\d{1,2}/art_[a-f0-9_]+\.html",
        "jyxx_deep4": r"/jyxx/(?:\d+/){3,}\d{8}/[a-f0-9\-]+\.html",
        "jyxx_deep": r"/jyxx/(?:\d+/){2}\d{8}/[a-f0-9\-]+\.html",
        "jyxx_mid": r"/jyxx/\d+/\d+/\d{8}/[a-f0-9\-]+\.html",
        "t_date": r"t\d{8}_\d+\.(?:s?html|htm)",
        "info_num": r"/info/\d+/\d+\.htm",
        "content_num": r"content[_-]?\d+\.(?:html|shtml)",
        "col_art": r"/col\d+/art/\d+/art_[a-f0-9]+\.html",
        "jhtml": r"\.jhtml",
        "shtml": r"\.shtml",
        "aspx": r"\.aspx",
        "jsp": r"\.jsp",
        "do_action": r"\.do\b",
        "query_detail": r"[?&](?:id|infoid|ItemId)=[a-f0-9\-]+",
    }
    filter_regex = filter_map.get(best, "")

    selector_map = {
        "art_date": "a[href*='/art/']",
        "col_art": "a[href*='/art/']",
        "jyxx_deep4": "a[href*='/jyxx/'], a[href*='.html']",
        "jyxx_deep": "a[href*='/jyxx/'], a[href*='.html']",
        "jyxx_mid": "a[href*='/jyxx/'], a[href*='.html']",
        "t_date": "a[href*='.shtml'], a[href*='.html']",
        "info_num": "a[href*='/info/']",
        "content_num": "a[href*='content_'], a[href*='/content/']",
        "jhtml": "a[href*='.jhtml'], a[href*='.html']",
        "shtml": "a[href*='.shtml'], a[href*='.html']",
        "aspx": "a[href*='.aspx']",
        "jsp": "a[href*='.jsp'], a[href*='.do'], a[href*='.html']",
        "do_action": "a[href*='.jsp'], a[href*='.do'], a[href*='.html']",
        "query_detail": "a[href*='?']",
    }
    item_selector = selector_map.get(best, "a[href*='.html'], a[href*='.shtml']")

    return item_selector, filter_regex


def _derive_first_page_url(html, url):
    """Find the most likely notice list page URL from HTML."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.hostname}"

    common_paths = [
        r'href=["\']([^"\']*(?:gsgg|tzgg|xxgk|zwgk|jyxx|gkxx|ggtz|zhxw|jydt|dtyw|gzdt|zygg)[^"\']*)["\']',
        r'href=["\']([^"\']*(?:通知公告|信息公开|交易信息|招标公告|政务公开|中标公示)[^"\']*)["\']',
    ]
    exclude_keywords = ['tradeInfo', 'trade_info', 'notice.', 'secondpage', 'moreinfo',
                        'about', 'search', 'login', 'register', 'javascript']

    candidates = []
    for pattern in common_paths:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            href = m.group(1)
            if re.search(r'\.(css|js|png|jpg|gif|ico|svg|woff|ttf|eot)(\?|$)', href, re.IGNORECASE):
                continue
            low = href.lower()
            if any(kw.lower() in low for kw in exclude_keywords):
                continue
            if href.startswith('http'):
                candidates.append(href)
            elif href.startswith('/'):
                candidates.append(base + href)
            elif href.startswith('.'):
                candidates.append(urljoin(url, href))

    if candidates:
        candidates.sort(key=len)
        return candidates[0]
    return None


def _detect_kb_domain(site_code, site_name="", url=""):
    """Infer knowledge base domain from site_code/site_name/url."""
    text = (site_code + site_name + url).lower()
    mapping = [
        ('ggzy', 'procurement'), ('jyzx', 'procurement'),
        ('fgw', 'development'), ('fagai', 'development'), ('ndrc', 'development'),
        ('zjj', 'construction'), ('zjt', 'construction'), ('zhujian', 'construction'), ('jsj', 'construction'),
        ('sthjj', 'environment'), ('shengtai', 'environment'), ('hbj', 'environment'),
        ('scjgj', 'regulation'), ('shichang', 'regulation'), ('amr', 'regulation'),
        ('yjglj', 'safety'), ('yingji', 'safety'), ('ajj', 'safety'),
        ('zrzy', 'resources'), ('ziran', 'resources'), ('gtzy', 'resources'),
        ('shuiwu', 'tax'), ('swj', 'tax'),
        ('slj', 'water'), ('shuili', 'water'), ('mwr', 'water'),
        ('jtj', 'transport'), ('jtys', 'transport'), ('jiaotong', 'transport'),
        ('czj', 'finance'), ('caizheng', 'finance'), ('mof', 'finance'),
        ('rsj', 'hr'), ('renshe', 'hr'), ('mohrss', 'hr'),
        ('sjj', 'audit'), ('shenji', 'audit'),
        ('nyj', 'energy'), ('nengyuan', 'energy'),
    ]
    for key, domain in mapping:
        if key in text:
            return domain
    return None


def _deep_copy(d):
    return json.loads(json.dumps(d))


def quick_config(url, site_name, site_code=None, fetcher=None):
    """One-shot site config generation.

    Fetches homepage, detects CMS signature, derives link patterns,
    finds best list page, and returns a ready-to-use SITE_CONFIG.

    Args:
        url: site homepage URL
        site_name: human-readable name
        site_code: optional site code (auto-derived if not provided)
        fetcher: optional fetch function (uses ggzy_crawler.fetcher.fetch if not provided)

    Returns:
        SITE_CONFIG dict ready for extract_list()
    """
    if fetcher is None:
        from ggzy_crawler.fetcher import fetch as _fetch
        fetcher = _fetch

    result = fetcher(url)
    if not result.ok:
        return _fallback_config(url, site_name, site_code)

    html = result.text

    if not site_code:
        site_code = _derive_site_code(url, site_name)

    scores = _score_cms(html, url)
    top_name, top_score = scores[0]

    derived_selector, derived_filter = _derive_patterns(html, url)
    first_page = _derive_first_page_url(html, url)

    sig = next((s for s in CMS_SIGNATURES if s["name"] == top_name), CMS_SIGNATURES[0])
    config = _deep_copy(sig["config"])
    config["site_code"] = site_code
    config["site_name"] = site_name
    config["base_url"] = url.rstrip("/")
    config["_detected_cms"] = sig["label"]
    config["_cms_score"] = top_score
    config["_all_scores"] = [(n, s) for n, s in scores[:5]]

    kb_domain = _detect_kb_domain(site_code, site_name, url)
    if kb_domain:
        config["kb_domain"] = kb_domain
        config["kb_content_type"] = "notices"

    list_cfg = config.setdefault("list", {})
    if derived_selector:
        list_cfg["item_selector"] = derived_selector
    if derived_filter:
        list_cfg["filter_href_include"] = derived_filter
    if first_page:
        list_cfg["url_template_first"] = first_page

    if top_name == "trs":
        col_match = re.search(r'/col/(col\d+)/', html)
        if col_match:
            col_id = col_match.group(1)
            list_cfg["url_template"] = f"/col/{col_id}/index_{{page}}.html"
            list_cfg["url_template_first"] = f"/col/{col_id}/index.html"

    home_matches = 0
    filter_re = list_cfg.get("filter_href_include", "")
    if filter_re:
        try:
            home_matches = len(re.findall(filter_re, html))
        except Exception:
            home_matches = 0
    if home_matches > 0:
        list_cfg["url_template_first"] = "/"
        list_cfg["max_pages"] = 1
        config["_homepage_items"] = home_matches

    if top_score < 3 and len(html) < 2000:
        config["engine"] = "list_pagination_browser"
        config["list"]["wait_ms"] = 3000

    config["_needs_review"] = (home_matches < 3)
    config["_homepage_items"] = home_matches
    if first_page and home_matches < 3:
        config["_suggested_list_page"] = first_page

    return config


def _derive_site_code(url, site_name):
    """Derive site_code from URL and site name."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    parts = hostname.split('.')

    dept_words = {
        'ggzy', 'ggzyjy', 'zjj', 'fgw', 'sthjj', 'scjgj', 'yjglj',
        'zrzy', 'zjt', 'jyzx', 'gzjy', 'ggj', 'jy', 'ggzyjyzx',
        'slj', 'jtj', 'jtys', 'jtysj', 'czj', 'rsj', 'sjj', 'nyj',
    }

    if len(parts) >= 3 and parts[-1] in ('cn', 'com', 'net'):
        if len(parts) >= 4:
            dept_part = parts[0]
            city_part = parts[1]
        else:
            city_part = parts[0]
            dept_part = 'procurement'

        dept = 'procurement'
        for dw in dept_words:
            if dept_part == dw or dept_part.startswith(dw):
                dept = dw.replace('ggzyjy', 'procurement').replace('jyzx', 'procurement').replace('gzjy', 'procurement')
                if 'zjj' in dept_part: dept = 'zjj'
                if 'fgw' in dept_part: dept = 'fgw'
                if 'sthjj' in dept_part: dept = 'sthjj'
                if 'scjgj' in dept_part: dept = 'scjgj'
                if 'yjglj' in dept_part: dept = 'yjglj'
                if 'zrzy' in dept_part: dept = 'zrzy'
                if 'zjt' in dept_part: dept = 'zjt'
                if 'slj' in dept_part: dept = 'slj'
                if 'jtj' in dept_part: dept = 'jtj'
                if 'czj' in dept_part: dept = 'czj'
                if 'rsj' in dept_part: dept = 'rsj'
                if 'sjj' in dept_part: dept = 'sjj'
                if 'nyj' in dept_part: dept = 'nyj'
                break
        city_pinyin = city_part
    else:
        city_pinyin = parts[0]
        dept = 'ggzy'

    city_pinyin = city_pinyin.lower().replace('-', '_')
    for suffix in ['_eweb', '_www', '_web', '_portal', '_jyzx']:
        if city_pinyin.endswith(suffix):
            city_pinyin = city_pinyin[:-len(suffix)]
    for prefix in ['www_', 'eweb_', 'web_']:
        if city_pinyin.startswith(prefix):
            city_pinyin = city_pinyin[len(prefix):]
    for suffix in ['-eweb', '-www', '-web', '-portal']:
        if dept.endswith(suffix):
            dept = dept[:-len(suffix)]

    if not city_pinyin or city_pinyin in ('www', 'eweb', 'index', 'web'):
        city_pinyin = 'unknown'

    return f"{city_pinyin}_{dept}"


def _fallback_config(url, site_name, site_code=None):
    """Fallback config when site is unreachable."""
    if not site_code:
        site_code = _derive_site_code(url, site_name)
    kb_domain = _detect_kb_domain(site_code, site_name, url)
    config = {
        "site_code": site_code,
        "site_name": site_name,
        "base_url": url.rstrip("/"),
        "engine": "list_pagination",
        "_detected_cms": "Unknown (unreachable)",
        "_cms_score": -1,
        "list": {
            "url_template_first": "/",
            "item_selector": "a[href*='.html'], a[href*='.shtml'], a[href*='/art/'], a[href*='/info/']",
            "max_pages": 1,
            "filter_href_exclude": ["index", "javascript", "about", "list", "nav_"],
        },
        "detail": {
            "fields": [
                {"name": "title", "selector": "title::text"},
                {"name": "content_text", "selector": "body *::text"},
            ],
        },
        "request": {"method": "GET", "rate_limit": 1.5, "timeout": 30},
    }
    if kb_domain:
        config["kb_domain"] = kb_domain
        config["kb_content_type"] = "notices"
    return config
