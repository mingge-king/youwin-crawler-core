"""Site exploration engine — pure rules, no config assumptions.

Probes each site to discover:
1. Homepage analysis: search inputs, CMS signature, list page patterns
2. Search probing: submit keywords, analyze result link distribution, detect pagination
3. Link classification: WeChat / internal / external / attachments
4. Strategy generation: output ready-to-use crawl config

Rule sources: hardcoded pattern libraries + CMS signature library.
LLM only used for post-failure diagnosis and rule supplementation.
"""
import re
import json
import time
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ── Search Patterns ──────────────────────────────────────────

SEARCH_PATTERNS = [
    {"name": "standard_search_input", "input_attrs": {"type": "search"}, "priority": 100},
    {
        "name": "text_input_with_search_placeholder",
        "input_attrs": {"type": "text"},
        "placeholder_keywords": ["搜索", "search", "请输入关键词", "请输入关键字", "全文检索"],
        "priority": 90,
    },
    {
        "name": "text_input_with_search_name",
        "input_attrs": {"type": "text"},
        "name_keywords": ["searchWord", "searchword", "keyword", "key", "q", "query", "search", "gjz", "title"],
        "priority": 85,
    },
    {
        "name": "text_input_with_search_id",
        "input_attrs": {"type": "text"},
        "id_keywords": ["search", "keyword", "query", "gjz", "title", "key"],
        "priority": 80,
    },
    {
        "name": "text_input_in_search_form",
        "input_attrs": {"type": "text"},
        "parent_form_has_search": True,
        "priority": 70,
    },
    {"name": "generic_text_input", "input_attrs": {"type": "text"}, "priority": 30},
]

SEARCH_FORM_PATTERNS = [
    (r'search\.(?:html|jhtml|shtml|aspx|php|jsp|do)', 10),
    (r'/search/', 9),
    (r'siteSearch|fullSearch|full_search|fullsearch', 8),
    (r'nxsearch/search', 9),
    (r'solr/', 8),
    (r'/search\b', 5),
]

DEFAULT_KEYWORDS = ["2025", "2024", "2023", "招标", "中标", "公告", "串通投标", "工程"]


# ── Pagination Patterns ──────────────────────────────────────

PAGINATION_PATTERNS = [
    (r'[?&](?:page|p|pageNo|pageIndex|pn|curPage|currentPage|page_num|pageNo|page_id)=(\d+)', "query_param"),
    (r'[?&](?:start|offset|begin)=(\d+)', "offset_param"),
    (r'/index[_\-]?(\d+)\.(?:html|shtml|jhtml)', "path_index_num"),
    (r'/_?(\d+)(?:\.(?:html|shtml|jhtml))?', "path_num"),
    (r'name=["\']?(?:page|pageNo|pageIndex)["\']?\s+value=["\']?(\d+)', "form_page"),
    (r'<a[^>]*>(?:下一页|下页|后页|next|>>|»|›|加载更多)</a>', "link_next"),
    (r'(?:goPage|gotoPage|jumpPage|paginate|loadMore|load_more)\s*\(\s*(\d+)\s*\)', "js_func"),
    (r'data-page=["\'](\d+)["\']', "data_page"),
]

WECHAT_PATTERNS = [
    r'mp\.weixin\.qq\.com/s/[A-Za-z0-9\-_]+',
    r'mp\.weixin\.qq\.com/s\?__biz=',
]


# ── Probe Result ──────────────────────────────────────────────

class ProbeResult:
    """Homepage probe result."""
    def __init__(self):
        self.url = ""
        self.domain = ""
        self.has_search = False
        self.search_inputs = []
        self.search_form_action = ""
        self.cms_signature = ""
        self.cms_score = 0
        self.list_page_links = []
        self.homepage_article_links = []
        self.needs_browser = False
        self.html_size = 0
        self.error = ""


class SearchProbeResult:
    """Search result analysis."""
    def __init__(self):
        self.keyword = ""
        self.search_url = ""
        self.result_html = ""
        self.total_links = 0
        self.wechat_links = []
        self.internal_links = []
        self.external_links = []
        self.attachment_links = []
        self.pagination_detected = False
        self.pagination_type = ""
        self.max_page = 1
        self.error = ""


# ── Main API ─────────────────────────────────────────────────

def probe(url, headless=True, timeout=30000, channel=None):
    """Probe site homepage — detect search inputs, CMS, link patterns.

    Args:
        url: site homepage URL
        headless: headless mode
        timeout: page load timeout (ms)
        channel: browser channel (None=chromium, "msedge"=Edge)

    Returns:
        ProbeResult
    """
    result = ProbeResult()
    result.url = url
    parsed = urlparse(url)
    result.domain = parsed.hostname or ""

    with sync_playwright() as p:
        launch_args = {"headless": headless}
        if channel:
            launch_args["channel"] = channel
        browser = p.chromium.launch(**launch_args)
        page = browser.new_page()
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except PlaywrightTimeout:
            try:
                page.goto(url, timeout=timeout, wait_until="commit")
                page.wait_for_timeout(5000)
            except Exception as e:
                result.error = str(e)[:200]
                browser.close()
                return result
        except Exception as e:
            result.error = str(e)[:200]
            browser.close()
            return result

        html = page.content()
        result.html_size = len(html)

        try:
            from playwright_stealth import Stealth
            Stealth().use_sync(page)
        except ImportError:
            pass

        result.search_inputs = _detect_search_inputs(page, html, result.domain)

        if result.search_inputs:
            result.has_search = True
            best = result.search_inputs[0]
            result.search_form_action = _determine_search_action(page, best, url)

        cms_name, cms_score = _detect_cms_from_html(html, url)
        result.cms_signature = cms_name
        result.cms_score = cms_score

        result.homepage_article_links = _extract_homepage_links(html, result.domain)
        result.needs_browser = _needs_browser_render(html, result)

        browser.close()

    return result


def explore_search(url, keyword="2025", search_input=None, search_action="",
                   headless=True, timeout=30000, channel=None):
    """Execute search probe — submit keyword, analyze results.

    Returns:
        SearchProbeResult
    """
    result = SearchProbeResult()
    result.keyword = keyword

    with sync_playwright() as p:
        launch_args = {"headless": headless}
        if channel:
            launch_args["channel"] = channel
        browser = p.chromium.launch(**launch_args)
        page = browser.new_page()
        try:
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
        except Exception as e:
            result.error = f"Homepage load failed: {e}"
            browser.close()
            return result

        pre_search_url = page.url

        try:
            if search_action and ('search' in search_action.lower() or '{keyword}' in search_action):
                search_url = search_action.replace("{keyword}", keyword)
                if not search_url.startswith("http"):
                    search_url = urljoin(url, search_url)
                page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)

            elif search_input and search_input.get("selector"):
                selector = search_input["selector"]
                try:
                    page.wait_for_selector(selector, timeout=5000)
                except PlaywrightTimeout:
                    pass

                page.click(selector)
                page.fill(selector, "")
                page.type(selector, keyword, delay=50)

                search_navigated = False
                try:
                    page.press(selector, "Enter")
                    page.wait_for_timeout(2000)
                    if page.url != pre_search_url:
                        search_navigated = True
                except Exception:
                    pass

                if not search_navigated:
                    button_selectors = [
                        'input[type="submit"]', 'button[type="submit"]',
                        'button:has-text("搜索")', 'button:has-text("检索")',
                        'input[value*="搜索"]', 'input[value*="检索"]',
                        'a:has-text("搜索")', '.search-btn', '#search-btn',
                        'button.search', '[class*="search"] button',
                        'form button', 'form input[type="submit"]',
                    ]
                    for btn_sel in button_selectors:
                        try:
                            btn = page.query_selector(btn_sel)
                            if btn:
                                btn.click()
                                page.wait_for_timeout(2000)
                                if page.url != pre_search_url:
                                    break
                        except Exception:
                            continue

                    if page.url == pre_search_url:
                        try:
                            page.evaluate(f"""(sel) => {{
                                const inp = document.querySelector(sel);
                                if (!inp) return;
                                const form = inp.closest('form');
                                if (form) form.submit();
                            }}""", selector)
                            page.wait_for_timeout(3000)
                        except Exception:
                            pass

                page.wait_for_timeout(4000)
            else:
                result.error = "No search entry point"
                browser.close()
                return result

            result.search_url = page.url
            result.result_html = page.content()

        except Exception as e:
            result.error = f"Search execution failed: {e}"
            browser.close()
            return result

        html = page.content()
        base_domain = urlparse(url).hostname or ""

        links = _extract_all_links_from_page(page, html)
        classified = classify_links(links, base_domain)

        result.wechat_links = classified["wechat"]
        result.internal_links = classified["internal"]
        result.external_links = classified["external"]
        result.attachment_links = classified["attachment"]
        result.total_links = len(links)

        pag_info = _detect_pagination(html, page.url)
        result.pagination_detected = pag_info["detected"]
        result.pagination_type = pag_info["type"]
        result.max_page = pag_info["max_page"]

        browser.close()

    return result


def explore(url, keywords=None, headless=True, timeout=30000, channel=None):
    """One-shot site exploration: probe -> search -> strategy.

    Returns:
        (ProbeResult, SearchProbeResult, dict)
    """
    kw = keywords or ["2025"]

    pr = probe(url, headless=headless, timeout=timeout, channel=channel)

    sr = None
    if pr.has_search and pr.search_inputs:
        best = pr.search_inputs[0]
        for keyword in kw:
            sr = explore_search(
                url, keyword=keyword, search_input=best,
                search_action=pr.search_form_action,
                headless=headless, timeout=timeout, channel=channel,
            )
            if not sr.error and sr.total_links > 0:
                break

    strategy = generate_strategy(pr, sr)
    return pr, sr, strategy


# ── Search API Detection ─────────────────────────────────────

def detect_search_api(html, url, page=None):
    """Detect search API endpoint from page HTML.

    Supports IRS variants:
    - POST JSON: /irs/front/search
    - GET query-string: /irs-common-search/search

    Returns API config dict or None.
    """
    base_url = f"{urlparse(url).scheme}://{urlparse(url).hostname}"

    if re.search(r'/irs/front/search|nxsearch/search\.html', html):
        tenant_id = _extract_tenant_id(html)
        config_tenant_id = _extract_config_tenant_id(html)
        data_type_id = _extract_data_type_id(html)
        return {
            "endpoint": urljoin(base_url, "/irs/front/search"),
            "method": "POST",
            "content_type": "application/json",
            "variant": "irs_post",
            "result_path": "data.middle.list",
            "total_path": "data.pager.total",
            "page_param": "pageNo",
            "page_size_param": "pageSize",
            "keyword_param": "searchWord",
            "items": ["url", "title", "title_no_tag", "time", "source"],
            "pagination_type": "json_pageNo",
            "tenant_id": str(tenant_id),
            "config_tenant_id": str(config_tenant_id),
            "data_type_id": data_type_id,
        }

    irs_common_match = re.search(r'/irs-common-search/search\?([^"\'\s]+)', html)
    if irs_common_match:
        query_string = irs_common_match.group(1)
        code_match = re.search(r'code=([^&\s"\']+)', query_string)
        code = code_match.group(1) if code_match else ""
        search_url = urljoin(base_url, f"/irs-common-search/search?code={code}")
        return {
            "endpoint": search_url,
            "method": "GET",
            "content_type": "",
            "variant": "irs_get",
            "result_path": "",
            "total_path": "",
            "page_param": "pageNo",
            "page_size_param": "pageSize",
            "keyword_param": "searchWord",
            "query_params": {
                "code": code, "configCode": "",
                "searchWord": "{keyword}", "orderBy": "related",
                "searchBy": "all", "pageNo": "{page}", "pageSize": "10",
                "isAdvancedSearch": "", "isDefaultAdvanced": "", "advancedFilters": "",
            },
            "items": [],
            "pagination_type": "query_param",
            "needs_browser": True,
        }

    if re.search(r'/search\.json|/api/search/', html):
        return {
            "endpoint": urljoin(base_url, "/search.json"),
            "method": "GET", "content_type": "", "variant": "generic_get",
            "result_path": "data", "total_path": "total",
            "page_param": "page", "page_size_param": "size",
            "keyword_param": "q", "items": ["url", "title"],
            "pagination_type": "query_param",
        }

    if page is not None:
        try:
            js_search = page.evaluate("""() => {
                const scripts = Array.from(document.querySelectorAll('script'));
                const results = [];
                for (const s of scripts) {
                    const text = s.textContent || s.innerText || '';
                    if (text.includes('/irs/front/search') || text.includes('search.json') || text.includes('/api/')) {
                        results.push(text.substring(0, 500));
                    }
                }
                return results;
            }""")
            for text in js_search:
                m = re.search(r'(/irs/front/search[^"\'\s]*)', text)
                if m:
                    return {
                        "endpoint": urljoin(base_url, "/irs/front/search"),
                        "method": "POST", "variant": "irs_post",
                        "content_type": "application/json",
                        "result_path": "data.middle.list",
                        "total_path": "data.pager.total",
                        "page_param": "pageNo", "page_size_param": "pageSize",
                        "keyword_param": "searchWord",
                        "items": ["url", "title", "title_no_tag", "time", "source"],
                        "pagination_type": "json_pageNo",
                        "tenant_id": str(_extract_tenant_id("")),
                        "config_tenant_id": str(_extract_config_tenant_id("")),
                        "data_type_id": _extract_data_type_id(""),
                    }
                api_match = re.search(r'(/api/[^"\'\s]+)', text)
                if api_match:
                    return {
                        "endpoint": urljoin(base_url, api_match.group(1)),
                        "method": "GET", "variant": "generic_api",
                        "result_path": "data", "total_path": "total",
                        "page_param": "page", "page_size_param": "size",
                        "keyword_param": "keyword",
                        "items": ["url", "title"],
                        "pagination_type": "query_param",
                    }
        except Exception:
            pass

    return None


def explore_search_api(api_config, keyword, page=1, page_size=10, timeout=30):
    """Call search API directly to get results.

    Supports variants: irs_post, irs_get, generic_get.
    Returns: {"items": [...], "total": N, "page": 1, "page_count": N, "error": ""}
    """
    import urllib.request
    import ssl
    import urllib.parse

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    result = {"items": [], "total": 0, "page": page, "page_count": 0, "error": ""}
    variant = api_config.get("variant", "")
    endpoint = api_config["endpoint"]

    if variant == "irs_post":
        body = {
            "tenantIds": api_config.get("tenant_id", "83"),
            "tenantId": api_config.get("tenant_id", "83"),
            "searchWord": keyword,
            "dataTypeId": api_config.get("data_type_id", 331),
            "historySearchWords": [],
            "orderBy": "related",
            "searchBy": "all",
            "pageNo": page,
            "pageSize": str(page_size),
            "endDateTime": "", "beginDateTime": "",
            "filters": [],
            "configTenantId": api_config.get("config_tenant_id", "19"),
            "customFilter": {"operator": "and", "properties": [], "filters": []},
        }
        req_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=req_body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json, text/javascript, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as e:
            result["error"] = str(e)[:200]
            return result

        if data is None or not data.get("success", True):
            result["error"] = f"API returned null: {str(data)[:100]}"
            return result

        data_section = data.get("data")
        if data_section is None:
            result["error"] = "API data field is null"
            return result

        items = data_section.get("middle", {}).get("list", [])
        if not isinstance(items, list):
            items = []
        pager = data_section.get("pager", {})
        result["total"] = pager.get("total", 0)
        result["page_count"] = pager.get("pageCount", 0)
        result["items"] = items
        return result

    if variant == "irs_get":
        result["error"] = "irs_get requires Playwright SPA rendering, use explore_search (browser mode)"
        return result

    if variant in ("generic_get", "generic_api"):
        qp = api_config.get("query_params", {})
        params = {}
        for k, v in qp.items():
            params[k] = str(v).replace("{keyword}", keyword).replace("{page}", str(page))
        query_str = urllib.parse.urlencode(params)
        full_url = f"{endpoint}?{query_str}"
        req = urllib.request.Request(
            full_url,
            headers={
                "Accept": "application/json, text/javascript, */*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
            method="GET"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception as e:
            result["error"] = str(e)[:200]
            return result

        items = data
        for key in api_config.get("result_path", "data").split("."):
            if isinstance(items, dict) and key:
                items = items.get(key, [])
            else:
                items = []
        if not isinstance(items, list):
            items = []
        result["total"] = 0
        result["items"] = items
        return result

    # Generic fallback
    try:
        if api_config.get("method", "GET") == "POST":
            body = {
                api_config.get("keyword_param", "keyword"): keyword,
                api_config.get("page_param", "page"): page,
                api_config.get("page_size_param", "size"): page_size,
            }
            req_body = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(endpoint, data=req_body,
                headers={"Content-Type": "application/json"})
        else:
            params = urllib.parse.urlencode({
                api_config.get("keyword_param", "q"): keyword,
                api_config.get("page_param", "page"): page,
                api_config.get("page_size_param", "size"): page_size,
            })
            req = urllib.request.Request(f"{endpoint}?{params}")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        result["items"] = data if isinstance(data, list) else []
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def explore_search_api_all(api_config, keywords, max_pages=0, base_domain=""):
    """Batch search multiple keywords via API, merge & deduplicate, classify links.

    Returns:
        (classified, stats) where classified = {wechat:[], internal:[], external:[], attachment:[]}
    """
    all_items = []
    seen_urls = set()
    stats = {"total_api_results": 0, "keywords_searched": 0}

    for kw in keywords:
        page = 1
        kw_items = 0
        while True:
            api_result = explore_search_api(api_config, kw, page=page, page_size=20)
            if api_result["error"]:
                break

            for item in api_result["items"]:
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    text = item.get("title_no_tag", "") or item.get("title", "")
                    text = re.sub(r'<[^>]+>', '', text)
                    all_items.append({
                        "text": text[:200], "href": url,
                        "time": item.get("time", ""),
                        "source": item.get("source", ""),
                    })
                    kw_items += 1

            if not api_result["items"]:
                break
            page_count = api_result.get("page_count", 0)
            if page_count and page >= page_count:
                break
            if max_pages and page >= max_pages:
                break
            page += 1

        stats["keywords_searched"] += 1
        stats["total_api_results"] += kw_items

    classified = classify_links(all_items, base_domain)
    return classified, stats


# ── Strategy Generation ──────────────────────────────────────

def generate_strategy(probe_result, search_result=None):
    """Generate crawl strategy from probe results.

    Returns dict ready to use as site config.
    """
    s = {
        "engine": "list_pagination",
        "has_search": probe_result.has_search,
        "needs_browser": probe_result.needs_browser,
        "link_summary": {"wechat": 0, "internal": 0, "external": 0, "attachment": 0},
        "search_config": {},
        "suggested_keywords": DEFAULT_KEYWORDS[:],
        "cms_signature": probe_result.cms_signature,
        "cms_score": probe_result.cms_score,
        "errors": [],
        "warnings": [],
    }

    if probe_result.error:
        s["errors"].append(probe_result.error)
        s["engine"] = "list_pagination"
        return s

    if search_result and search_result.error:
        s["warnings"].append(f"Search probe failed: {search_result.error}")

    has_search = probe_result.has_search and search_result is not None and not search_result.error

    if has_search:
        s["link_summary"] = {
            "wechat": len(search_result.wechat_links),
            "internal": len(search_result.internal_links),
            "external": len(search_result.external_links),
            "attachment": len(search_result.attachment_links),
        }

        wechat_count = len(search_result.wechat_links)
        internal_count = len(search_result.internal_links)

        if wechat_count > 0 and wechat_count / max(search_result.total_links, 1) > 0.3:
            s["engine"] = "search_query_browser"
            s["warnings"].append(f"WeChat link ratio {wechat_count}/{search_result.total_links}")
        elif probe_result.needs_browser:
            s["engine"] = "search_query_browser"
        else:
            s["engine"] = "search_query"

        if probe_result.search_inputs:
            best_input = probe_result.search_inputs[0]
            s["search_config"] = {
                "input_selector": best_input["selector"],
                "input_name": best_input.get("name", ""),
                "form_action": probe_result.search_form_action or "",
                "keyword_field": _guess_keyword_param(best_input),
                "page_field": _guess_page_param(search_result),
                "result_item_selector": _derive_item_selector(search_result),
                "max_pages": search_result.max_page if search_result and search_result.pagination_detected else 10,
                "wait_ms": 4000,
            }
    else:
        if probe_result.needs_browser:
            s["engine"] = "list_pagination_browser"
        else:
            s["engine"] = "list_pagination"

        s["link_summary"] = {"internal": len(probe_result.homepage_article_links)}
        if not probe_result.homepage_article_links:
            s["warnings"].append("No article links found on homepage, search entry may be needed")

    return s


# ── Link Classification ──────────────────────────────────────

def classify_links(links, base_domain):
    """Classify links: WeChat / internal / external / attachment."""
    result = {"wechat": [], "internal": [], "external": [], "attachment": []}
    attachment_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                       '.zip', '.rar', '.7z', '.txt', '.csv'}

    for link in links:
        href = link.get("href", "")
        if not href:
            continue

        lower = href.lower().split("?")[0]
        is_attachment = False
        for ext in attachment_exts:
            if lower.endswith(ext):
                result["attachment"].append({**link, "ext": ext})
                is_attachment = True
                break
        if is_attachment:
            continue

        for pat in WECHAT_PATTERNS:
            if re.search(pat, href):
                result["wechat"].append(link)
                break
        else:
            try:
                link_domain = urlparse(href).hostname or ""
            except Exception:
                link_domain = ""

            if not link_domain or link_domain == base_domain:
                result["internal"].append(link)
            elif _is_same_site(link_domain, base_domain):
                result["internal"].append(link)
            else:
                result["external"].append(link)

    return result


# ── Internal Helpers ─────────────────────────────────────────

def _detect_search_inputs(page, html, domain):
    found = []
    try:
        inputs = page.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="search"], input[type="text"]');
            return Array.from(inputs).map(inp => ({
                type: inp.type || 'text', name: inp.name || '', id: inp.id || '',
                placeholder: inp.placeholder || '', className: inp.className || '',
                formAction: inp.closest('form') ? inp.closest('form').action || '' : '',
                formId: inp.closest('form') ? inp.closest('form').id || '' : '',
                visible: inp.offsetParent !== null,
                selector: '#' + inp.id || inp.name || inp.className.split(' ')[0] || 'input[type="' + inp.type + '"]'
            }));
        }""")
    except Exception:
        inputs = _parse_inputs_from_html(html)

    if not inputs:
        return []

    for inp in inputs:
        if not inp.get("visible", True):
            continue

        score = 0
        matched_pattern = ""
        for pat in SEARCH_PATTERNS:
            attrs = pat.get("input_attrs", {})

            if attrs.get("type") == "search" and inp.get("type") == "search":
                score = pat["priority"]
                matched_pattern = pat["name"]
                break

            if attrs.get("type") == "text":
                pkw = pat.get("placeholder_keywords", [])
                if pkw:
                    ph = inp.get("placeholder", "").lower()
                    if any(k.lower() in ph for k in pkw):
                        score = pat["priority"]
                        matched_pattern = pat["name"]
                        break
                nkw = pat.get("name_keywords", [])
                if nkw:
                    nm = inp.get("name", "").lower()
                    if any(k.lower() == nm.lower() for k in nkw):
                        score = pat["priority"]
                        matched_pattern = pat["name"]
                        break
                ikw = pat.get("id_keywords", [])
                if ikw:
                    iid = inp.get("id", "").lower()
                    if any(k.lower() in iid for k in ikw):
                        score = pat["priority"]
                        matched_pattern = pat["name"]
                        break
                if pat.get("parent_form_has_search"):
                    fa = inp.get("formAction", "").lower()
                    if any(k in fa for k in ["search", "query", "find"]):
                        score = pat["priority"]
                        matched_pattern = pat["name"]
                        break
                if pat["name"] == "generic_text_input" and score == 0:
                    score = pat["priority"]
                    matched_pattern = pat["name"]

        if score > 0:
            selector = _build_input_selector(inp)
            found.append({
                "selector": selector, "type": inp.get("type", "text"),
                "name": inp.get("name", ""), "id": inp.get("id", ""),
                "placeholder": inp.get("placeholder", ""),
                "form_action": inp.get("formAction", ""),
                "form_id": inp.get("formId", ""),
                "pattern": matched_pattern, "score": score,
            })

    found.sort(key=lambda x: x["score"], reverse=True)
    return found


def _parse_inputs_from_html(html):
    results = []
    for m in re.finditer(r'<input\s+([^>]*?\btype=["\'](?:search|text)["\'][^>]*)>', html, re.IGNORECASE):
        attrs_str = m.group(1)
        inp = {"type": "text", "name": "", "id": "", "placeholder": "", "formAction": "", "visible": True}
        if 'type="search"' in attrs_str or "type='search'" in attrs_str:
            inp["type"] = "search"
        nm = re.search(r'\bname=["\']([^"\']+)["\']', attrs_str)
        if nm: inp["name"] = nm.group(1)
        iid = re.search(r'\bid=["\']([^"\']+)["\']', attrs_str)
        if iid: inp["id"] = iid.group(1)
        ph = re.search(r'\bplaceholder=["\']([^"\']*)["\']', attrs_str)
        if ph: inp["placeholder"] = ph.group(1)
        results.append(inp)
    return results


def _build_input_selector(inp):
    if inp.get("id"):
        return f"#{inp['id']}"
    if inp.get("name"):
        return f'input[name="{inp["name"]}"]'
    if inp.get("placeholder"):
        return f'input[placeholder*="{inp["placeholder"][:20]}"]'
    return f'input[type="{inp.get("type", "text")}"]'


def _determine_search_action(page, best_input, base_url):
    selector = best_input.get("selector", "")
    current_url = page.url

    try:
        html = page.content()
        nx_match = re.search(r'nxsearch/search\.html\?[^"\'\s]+', html)
        if nx_match:
            nx_url = nx_match.group(0)
            if 'searchWord=' in nx_url:
                base_nx = nx_url.split('searchWord=')[0] + 'searchWord='
                return urljoin(base_url, base_nx) + '{keyword}'
            return urljoin(base_url, nx_url)

        code_match = re.search(r'(?:code|siteId|site_id)\s*[:=]\s*["\']([^"\']+)["\']', html)
        tenant_match = re.search(r'(?:tenantId|tenant_id)\s*[:=]\s*["\']([^"\']+)["\']', html)
        if code_match and tenant_match:
            return f"/nxsearch/search.html?code={code_match.group(1)}&tenantId={tenant_match.group(1)}&searchWord={{keyword}}"

        for sap in [
            r'(?:searchUrl|search_url|searchPath|search_path)\s*[:=]\s*["\']([^"\']+)["\']',
            r'(?:url|action)\s*[:=]\s*["\']([^"\']*search[^"\']*)["\']',
        ]:
            m = re.search(sap, html, re.IGNORECASE)
            if m:
                candidate = m.group(1)
                if candidate and not candidate.startswith("javascript:"):
                    return urljoin(base_url, candidate)
    except Exception:
        pass

    if best_input.get("form_action"):
        action = best_input["form_action"]
        if action and not action.startswith("javascript:") and action.strip():
            return urljoin(current_url, action)

    try:
        action = page.evaluate(f"""(sel) => {{
            const el = document.querySelector(sel);
            if (!el) return '';
            const form = el.closest('form');
            if (form) {{
                const a = form.action || '';
                if (a && !a.startsWith('javascript:') && a !== window.location.href) return a;
            }}
            return '';
        }}""", selector)
        if action and not action.startswith("javascript:") and not action.startswith("#"):
            return urljoin(current_url, action)
    except Exception:
        pass

    try:
        all_links = page.evaluate("""() => {
            const urls = [];
            document.querySelectorAll('script[src]').forEach(s => urls.push(s.src));
            document.querySelectorAll('link[href]').forEach(l => urls.push(l.href));
            return urls.join(' ');
        }""")
        for pat, _ in SEARCH_FORM_PATTERNS:
            m = re.search(pat, all_links)
            if m:
                found = m.group(1) if m.lastindex else m.group(0)
                return urljoin(base_url, found)
    except Exception:
        pass

    try:
        html = page.content()
        for pat, _ in SEARCH_FORM_PATTERNS:
            matches = list(re.finditer(pat, html))
            if matches:
                m = matches[0]
                href = m.group(1) if m.lastindex else m.group(0)
                return urljoin(base_url, href)
    except Exception:
        pass

    return ""


def _detect_cms_from_html(html, url):
    from ggzy_crawler.cms_detector import _score_cms
    scores = _score_cms(html, url)
    if scores and scores[0][1] > 0:
        return scores[0][0], scores[0][1]
    return "unknown", 0


def _extract_homepage_links(html, domain):
    links = []
    date_href_pat = re.compile(
        r'href=["\']([^"\']*(?:t\d{8}_\d+|/art/\d{4}/\d{1,2}/\d{1,2}/art_|'
        r'/\d{8}/[a-f0-9\-]+\.html|/\d{4}-\d{2}/\d+/[a-z0-9]+\.s?html|'
        r'content[_-]?\d+\.)[^"\']*)["\']',
        re.IGNORECASE
    )
    for m in date_href_pat.finditer(html):
        href = m.group(1)
        if re.search(r'\.(css|js|png|jpg|gif|ico)(\?|$)', href, re.IGNORECASE):
            continue
        links.append(href)
    return links[:50]


def _needs_browser_render(html, result):
    spa_indicators = ['vue', 'react', 'webpack', 'chunk', '__NUXT__', '__NEXT_DATA__']
    html_lower = html.lower()
    for ind in spa_indicators:
        if ind in html_lower:
            return True
    if len(html) < 2000:
        return True
    if result.cms_signature in ("epoint_browser", "huilan_hnsggzy"):
        return True
    return False


def _extract_all_links_from_page(page, html):
    links = []
    try:
        links = page.evaluate("""() => {
            const links = [];
            document.querySelectorAll('a[href]').forEach(a => {
                links.push({
                    text: (a.textContent || '').trim().substring(0, 200),
                    href: a.href
                });
            });
            return links;
        }""")
    except Exception:
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.IGNORECASE):
            links.append({"text": m.group(2).strip()[:200], "href": m.group(1)})
    return links or []


def _is_same_site(domain1, domain2):
    if not domain1 or not domain2:
        return False
    if domain1 == domain2:
        return True
    parts1 = domain1.split(".")
    parts2 = domain2.split(".")
    if len(parts1) >= 3 and len(parts2) >= 3:
        if parts1[-2] in ("gov", "com", "org", "net") and parts1[-1] == "cn":
            return ".".join(parts1[-3:]) == ".".join(parts2[-3:])
        if parts1[-1] in ("com", "cn", "org", "net"):
            return ".".join(parts1[-2:]) == ".".join(parts2[-2:])
    return False


def _detect_pagination(html, url):
    result = {"detected": False, "type": "", "max_page": 1}
    for pattern, ptype in PAGINATION_PATTERNS:
        matches = list(re.finditer(pattern, html, re.IGNORECASE))
        if matches:
            result["detected"] = True
            result["type"] = ptype
            if ptype in ("query_param", "offset_param"):
                pages = []
                for m in matches:
                    try:
                        pages.append(int(m.group(1)))
                    except ValueError:
                        continue
                result["max_page"] = min(max(pages) if pages else 1, 500)
            elif ptype == "path_index_num":
                pages = []
                for m in matches:
                    try:
                        pages.append(int(m.group(1)))
                    except ValueError:
                        continue
                result["max_page"] = min(max(pages) if pages else 1, 500)
            elif ptype == "link_next":
                result["max_page"] = 1
            break
    return result


def _guess_keyword_param(best_input):
    name = best_input.get("name", "").lower()
    name_map = {"searchword": "searchWord", "keyword": "keyword", "key": "key",
                "q": "q", "query": "query", "gjz": "gjz", "title": "title", "search": "search"}
    return name_map.get(name, "searchWord")


def _guess_page_param(search_result):
    if not search_result or not search_result.pagination_detected:
        return "page"
    ptype = search_result.pagination_type
    return "start" if ptype == "offset_param" else "page"


def _derive_item_selector(search_result):
    if not search_result:
        return "a[href]"
    if search_result.wechat_links:
        return "a[href*='mp.weixin.qq.com']"
    if search_result.internal_links:
        hrefs = [l["href"] for l in search_result.internal_links[:50]]
        patterns = []
        for h in hrefs:
            for kw in [".shtml", ".jhtml", ".html", "/art/", "/info/", "/content/"]:
                if kw in h:
                    patterns.append(kw.replace("/", "").replace(".", ""))
        if patterns:
            most = max(set(patterns), key=patterns.count)
            if most in ("shtml", "jhtml", "html"):
                return f"a[href*='.{most}']"
            elif most in ("art", "info", "content"):
                return f"a[href*='/{most}/']"
    return "a[href]"


def _extract_tenant_id(html):
    if not html:
        return 83
    m = re.search(r'tenantId[=:]\s*["\']?(\d+)', html, re.IGNORECASE)
    return int(m.group(1)) if m else 83


def _extract_config_tenant_id(html):
    if not html:
        return 19
    m = re.search(r'configTenantId[=:]\s*["\']?(\d+)', html, re.IGNORECASE)
    return int(m.group(1)) if m else 19


def _extract_data_type_id(html):
    if not html:
        return 331
    m = re.search(r'dataTypeId[=:]\s*["\']?(\d+)', html, re.IGNORECASE)
    return int(m.group(1)) if m else 331
