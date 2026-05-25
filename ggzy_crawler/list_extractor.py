"""Universal list extractor: supports search-query and list-pagination engines.

Engine types:
- list_pagination: HTTP + CSS selectors
- list_pagination_browser: Playwright browser + CSS selectors (JS-rendered sites)
- search_query: search form submission
- search_query_browser: Playwright browser search
- api_json: JSON API extraction

Multi-keyword support with automatic pagination and deduplication.
"""
import re
import threading
from urllib.parse import urljoin, urlparse

from ggzy_crawler.fetcher import fetch, FetchResult


# Browser pool for list_pagination_browser engine
_browser_pool = []
_browser_semaphore = threading.Semaphore(8)
_browser_pool_lock = threading.Lock()
MAX_BROWSER_INSTANCES = 8
_domain_semaphores = {}
_domain_sem_lock = threading.Lock()
MAX_PER_DOMAIN = 2


def extract_links(html_or_resp, item_selector, link_selector=None, base_url="", page_url="",
                  filter_href_exclude=None, filter_href_include=None,
                  href_pattern=None, href_replacement=None):
    """Extract links and text from a list page.

    Args:
        html_or_resp: FetchResult or Scrapling response
        item_selector: CSS selector for list items
        link_selector: optional more specific link selector within each item
        base_url: for resolving relative URLs
        page_url: page URL (takes precedence over base_url for relative resolution)
        filter_href_exclude: list of substrings to exclude
        filter_href_include: regex pattern links must match
        href_pattern: regex to extract URL from JS/non-standard href
        href_replacement: template to build URL from href_pattern groups
    """
    if isinstance(html_or_resp, FetchResult):
        resp = html_or_resp._resp
    else:
        resp = html_or_resp

    resolve_base = page_url or base_url
    exclude = filter_href_exclude or []
    include_pat = re.compile(filter_href_include) if filter_href_include else None
    href_pat = re.compile(href_pattern) if href_pattern else None

    items = []
    elements = resp.css(item_selector)
    for el in elements:
        text_nodes = el.css('::text').getall()
        text = ''.join(text_nodes).strip() if text_nodes else str(el.text or "").strip()
        href = ""
        if link_selector:
            a = el.css(link_selector)
            if a:
                href = a[0].attrib.get("href", "")
        else:
            a_tags = el.css("a[href]")
            if a_tags:
                href = a_tags[0].attrib.get("href", "")

        if not href:
            href = el.attrib.get("href", "")

        if not href:
            onclick = el.attrib.get("onclick", "")
            if not onclick:
                children_with_onclick = el.css("[onclick]")
                if children_with_onclick:
                    onclick = children_with_onclick[0].attrib.get("onclick", "")
            m = re.search(r"""['"\\(](/\w[\w/.-]*\.(?:j?html))['"\\)]""", onclick)
            if not m:
                m = re.search(r"""['"\\(](/\w+/\d+[^'"\\)]*)['"\\)]""", onclick)
            if m:
                href = m.group(1)

        if not href:
            continue

        if any(x in href for x in exclude):
            continue
        if include_pat and not include_pat.search(href):
            continue

        if href_pat:
            m = href_pat.search(href)
            if m:
                href = href_replacement
                href = href.replace('{0}', m.group(0))
                for i, group in enumerate(m.groups()):
                    href = href.replace('{' + str(i+1) + '}', group)
            else:
                continue

        if not href.startswith("http") and resolve_base:
            href = urljoin(resolve_base, href)

        items.append({"text": text, "href": href})

    return items


def _extract_one_page(config, page, keyword, base_url, list_cfg, next_url=None):
    """Extract links from a single page (HTTP engine)."""
    if config.get("engine") == "search_query" and keyword:
        search_cfg = config["search"]
        url = base_url.rstrip("/") + "/" + search_cfg["url"].lstrip("/")
        params = {}
        for k, v in search_cfg.get("params", {}).items():
            params[k] = str(v).replace("{keyword}", keyword).replace("{page}", str(page))
        result = fetch(url, method=search_cfg.get("method", "GET"), params=params)
    else:
        if next_url:
            url = urljoin(base_url, next_url)
        elif page == 1 and list_cfg.get("url_template_first"):
            url_template = list_cfg["url_template_first"]
            url = base_url.rstrip("/") + "/" + url_template.lstrip("/")
            url = url.replace("{page}", str(page))
        else:
            url_template = list_cfg.get("url_template", "")
            url = base_url.rstrip("/") + "/" + url_template.lstrip("/")
            url = url.replace("{page}", str(page))

        post_data = None
        req_method = list_cfg.get("method", "GET")
        extra_headers = list_cfg.get("headers") or {}
        if req_method.upper() == "POST":
            post_data = {}
            for k, v in list_cfg.get("post_data", {}).items():
                post_data[k] = str(v).replace("{page}", str(page))
        result = fetch(url, method=req_method, data=post_data, headers=extra_headers if extra_headers else None)

    if not result.ok:
        return [], result

    items = extract_links(
        result,
        item_selector=list_cfg["item_selector"],
        link_selector=list_cfg.get("link_selector"),
        base_url=base_url, page_url=url,
        filter_href_exclude=list_cfg.get("filter_href_exclude"),
        filter_href_include=list_cfg.get("filter_href_include"),
        href_pattern=list_cfg.get("href_pattern"),
        href_replacement=list_cfg.get("href_replacement"),
    )

    if not items and list_cfg.get("regex_pattern"):
        pattern = re.compile(list_cfg["regex_pattern"])
        for m in pattern.finditer(result.text):
            href = m.group(1)
            text = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            if not href.startswith("http") and base_url:
                href = urljoin(base_url, href)
            items.append({"text": text.strip(), "href": href})

    return items, result


def _get_browser():
    """Get an idle BrowserFetcher from the pool."""
    from ggzy_crawler.anti_bot import BrowserFetcher
    _browser_semaphore.acquire()
    with _browser_pool_lock:
        if _browser_pool:
            return _browser_pool.pop()
    try:
        b = BrowserFetcher(headless=True, timeout=30000)
        b.start()
        return b
    except Exception:
        _browser_semaphore.release()
        raise


def _return_browser(browser):
    """Return BrowserFetcher to the pool."""
    with _browser_pool_lock:
        if len(_browser_pool) < MAX_BROWSER_INSTANCES:
            _browser_pool.append(browser)
        else:
            try:
                browser.stop()
            except Exception:
                pass
    _browser_semaphore.release()


def _extract_one_page_browser(config, page, base_url, list_cfg, next_url=None):
    """Extract links from a single page (browser engine)."""
    from scrapling import Selector

    if next_url:
        url = urljoin(base_url, next_url)
    elif page == 1 and list_cfg.get("url_template_first"):
        url_template = list_cfg["url_template_first"]
        url = base_url.rstrip("/") + "/" + url_template.lstrip("/")
        url = url.replace("{page}", str(page))
    else:
        url_template = list_cfg.get("url_template", "")
        url = base_url.rstrip("/") + "/" + url_template.lstrip("/")
        url = url.replace("{page}", str(page))

    # Domain-level concurrency control
    domain = urlparse(url).hostname or ""
    with _domain_sem_lock:
        if domain not in _domain_semaphores:
            _domain_semaphores[domain] = threading.Semaphore(MAX_PER_DOMAIN)
        domain_sem = _domain_semaphores[domain]
    domain_sem.acquire()

    browser = _get_browser()
    try:
        html = browser.fetch(url,
                             wait_ms=list_cfg.get("wait_ms", 6000),
                             wait_for_selector=list_cfg.get("wait_for_selector"))
    except Exception:
        _return_browser(browser)
        domain_sem.release()
        return [], type('FakeResult', (), {'ok': False, 'status': 0, 'size': 0, 'url': url, 'text': '', '_resp': None})()

    _return_browser(browser)
    domain_sem.release()

    try:
        resp = Selector(html)
    except Exception:
        return [], type('FakeResult', (), {'ok': False, 'status': 0, 'size': len(html), 'url': url, 'text': html, '_resp': None})()

    items = extract_links(
        resp,
        item_selector=list_cfg["item_selector"],
        link_selector=list_cfg.get("link_selector"),
        base_url=base_url, page_url=url,
        filter_href_exclude=list_cfg.get("filter_href_exclude"),
        filter_href_include=list_cfg.get("filter_href_include"),
        href_pattern=list_cfg.get("href_pattern"),
        href_replacement=list_cfg.get("href_replacement"),
    )

    if not items and list_cfg.get("regex_pattern"):
        pattern = re.compile(list_cfg["regex_pattern"])
        for m in pattern.finditer(html):
            href = m.group(1)
            text = m.group(2) if m.lastindex and m.lastindex >= 2 else ""
            if not href.startswith("http") and base_url:
                href = urljoin(base_url, href)
            items.append({"text": text.strip(), "href": href})

    result = type('FakeResult', (), {'ok': len(items) > 0, 'status': 200, 'size': len(html),
                                      'text': html, '_resp': resp, 'url': url})()
    return items, result


def _extract_one_page_api_json(config, page, base_url, api_cfg):
    """Extract from JSON API page (supports GET/POST, encryption, HTML-in-JSON)."""
    from urllib.parse import urlencode
    import json as _json

    headers = dict(api_cfg.get("headers") or {})
    method = api_cfg.get("method", "GET").upper()
    content_type = api_cfg.get("content_type", "")
    page_size = api_cfg.get("page_size", 10)

    if method == "POST":
        url_tpl = api_cfg.get("url_template", "") or api_cfg.get("url", "")
        if url_tpl.startswith("http"):
            url = url_tpl
        else:
            url = base_url.rstrip("/") + "/" + url_tpl.lstrip("/")

        body_template = api_cfg.get("body_template") or api_cfg.get("params") or {}

        if content_type == "application/json":
            body_copy = {}
            for k, v in body_template.items():
                if isinstance(v, str):
                    v = v.replace("{page}", str(page))
                    if "{page_offset}" in v:
                        body_copy[k] = (page - 1) * page_size
                    else:
                        body_copy[k] = v
                elif isinstance(v, list):
                    body_copy[k] = _json.loads(
                        _json.dumps(v).replace("{page}", str(page)))
                else:
                    body_copy[k] = v

            sign_cfg = api_cfg.get("sign")
            if sign_cfg:
                import hashlib
                sign_key = sign_cfg["key"]
                sign_header = sign_cfg.get("header_name", "portal-sign")
                cleaned = {}
                for sk, sv in body_copy.items():
                    if sv != "" and sv is not None:
                        cleaned[sk] = sv
                sorted_keys = sorted(cleaned.keys(), key=lambda x: x.upper())
                parts = []
                for sk in sorted_keys:
                    sval = cleaned[sk]
                    if isinstance(sval, (dict, list)):
                        parts.append(sk + _json.dumps(sval, separators=(',', ':'), ensure_ascii=False))
                    else:
                        parts.append(sk + str(sval))
                sign_str = sign_key + ''.join(parts)
                sign_val = hashlib.md5(sign_str.encode('utf-8')).hexdigest().lower()
                headers[sign_header] = sign_val

            post_data = _json.dumps(body_copy).encode('utf-8')
        elif content_type == "application/x-www-form-urlencoded":
            post_data = {}
            for k, v in body_template.items():
                post_data[k] = str(v).replace("{page}", str(page))
                if "{page_offset}" in str(post_data[k]):
                    post_data[k] = (page - 1) * page_size
            post_data = urlencode(post_data)
        else:
            post_data = {}
            for k, v in body_template.items():
                post_data[k] = str(v).replace("{page}", str(page))
            post_data = urlencode(post_data)

        if content_type:
            headers["Content-Type"] = content_type
        result = fetch(url, method="POST", data=post_data, headers=headers if headers else None)
    else:
        url_tpl = api_cfg.get("url", "") or api_cfg.get("url_template", "")
        if url_tpl.startswith("http"):
            url = url_tpl
        else:
            url = base_url.rstrip("/") + "/" + url_tpl.lstrip("/")
        params = {}
        for k, v in api_cfg.get("params", {}).items():
            params[k] = str(v).replace("{page}", str(page))
        qs = urlencode(params)
        full_url = f"{url}?{qs}"
        result = fetch(full_url, method="GET", headers=headers if headers else None)

    if not result.ok:
        return [], result

    # Response decryption
    decrypt_cfg = api_cfg.get("response_decrypt")
    if decrypt_cfg:
        import base64 as _base64
        try:
            from Crypto.Cipher import AES as _AES
            from Crypto.Util.Padding import unpad as _unpad
        except ImportError:
            return [], type('FakeResult', (), {'ok': False, 'status': 0, 'size': 0,
                'text': 'Error: pycryptodome not installed (pip install pycryptodome)', '_resp': None})()
        raw = _json.loads(result.text)
        enc_data = raw.get(decrypt_cfg.get("data_field", "Data"), "")
        if enc_data:
            key = decrypt_cfg["key"].encode('utf-8')
            iv = decrypt_cfg["iv"].encode('utf-8')
            cipher = _AES.new(key, _AES.MODE_CBC, iv)
            decrypted = _unpad(cipher.decrypt(_base64.b64decode(enc_data)), _AES.block_size)
            result.text = decrypted.decode('utf-8')

    try:
        data = _json.loads(result.text)
    except Exception:
        json_re = api_cfg.get("json_extract_regex", "")
        if json_re:
            m = re.search(json_re, result.text, re.DOTALL)
            if m:
                json_str = m.group(1)
                json_fix = api_cfg.get("json_extract_fix", "")
                if json_fix:
                    json_str = json_str.replace(json_fix.split("->")[0], json_fix.split("->")[1])
                try:
                    data = _json.loads(json_str)
                except Exception:
                    return [], result
            else:
                return [], result
        elif api_cfg.get("html_item_regex"):
            item_re = api_cfg["html_item_regex"]
            item_matches = re.findall(item_re, result.text, re.DOTALL)
            if not item_matches:
                return [], result
            href_re = api_cfg.get("item_href_re", r"<a\s+href=\"([^\"]+)\"")
            text_re = api_cfg.get("item_text_re", r"<a[^>]*>\s*(.*?)\s*</a>")
            extra_re = api_cfg.get("item_extra_re", {})
            items = []
            href_filter = api_cfg.get("item_href_filter", "")
            for item_html in item_matches:
                h_m = re.search(href_re, item_html)
                if not h_m:
                    continue
                href = h_m.group(1)
                if href_filter and not re.search(href_filter, href):
                    continue
                if not href.startswith("http"):
                    href = base_url.rstrip("/") + "/" + href.lstrip("/")
                t_m = re.search(text_re, item_html, re.DOTALL)
                text = t_m.group(1).strip() if t_m else ""
                text = re.sub(r"<[^>]+>", "", text).strip()
                item = {"href": href, "text": text[:200]}
                for ef_name, ef_re in extra_re.items():
                    ef_m = re.search(ef_re, item_html)
                    if ef_m:
                        item[ef_name] = ef_m.group(1).strip()
                items.append(item)
            return items, result
        else:
            return [], result

    if isinstance(data, list):
        items_raw = data
    else:
        item_path = (api_cfg.get("items_path") or api_cfg.get("item_path") or "data").split(".")
        items_raw = data
        for key in item_path:
            if isinstance(items_raw, dict):
                items_raw = items_raw.get(key, [])
            elif isinstance(items_raw, str):
                try:
                    items_raw = _json.loads(items_raw)
                    if isinstance(items_raw, list):
                        break
                    items_raw = items_raw.get(key, []) if isinstance(items_raw, dict) else []
                except Exception:
                    items_raw = []
                    break
            else:
                items_raw = []
                break
        if not isinstance(items_raw, list):
            items_raw = []

    href_tpl = api_cfg.get("href_template", "")
    href_field = api_cfg.get("href_field", "sourceDataKey")
    text_field = api_cfg.get("text_field", "noticeName")
    extra_fields = api_cfg.get("extra_fields", [])

    items = []
    for row in items_raw:
        if href_tpl:
            href = href_tpl
            for fk, fv in row.items():
                href = href.replace("{" + fk + "}", str(fv or ""))
        else:
            href = str(row.get(href_field, ""))
        text = str(row.get(text_field, "") or "")
        if not href:
            continue
        if not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")
        item = {"href": href, "text": text[:200]}
        for ef in extra_fields:
            if isinstance(ef, dict):
                item[ef.get('name', ef.get('path', ''))] = row.get(ef.get('path', ef.get('name', '')), "")
            else:
                item[ef] = row.get(ef, "")
        items.append(item)

    return items, result


def _cleanup_browser():
    """Clean up all browser instances in the pool."""
    with _browser_pool_lock:
        for b in _browser_pool:
            try:
                b.stop()
            except Exception:
                pass
        _browser_pool.clear()


# ── Main API ─────────────────────────────────────────────────

def extract_list(config, page=1, keyword=None, keywords=None, page_callback=None,
                 start_page=1, end_page=0):
    """Universal list extraction with automatic pagination.

    Engine types:
    - list_pagination: HTTP + CSS selectors
    - list_pagination_browser: Playwright browser + CSS selectors
    - search_query: search form submission
    - api_json: JSON API extraction

    Multi-keyword: keywords=["2025","2024","2023","招标"] iterates each keyword
    with max_pages, merges, and deduplicates results.

    Args:
        config: site config dict with 'base_url', 'list', 'engine' keys
        page: starting page number (for single-page use)
        keyword: single keyword (for single-keyword use)
        keywords: list of keywords for multi-keyword rotation
        page_callback: called with (items, page) after each page
        start_page: resume from this page
        end_page: stop at this page (0=unlimited)

    Returns:
        (all_items, last_result)
    """
    base_url = config["base_url"]
    list_cfg = config["list"]
    max_pages = min(list_cfg.get("max_pages", 1), end_page) if end_page > 0 else list_cfg.get("max_pages", 1)
    engine_type = config.get("engine", "list_pagination")
    use_browser = engine_type in ("list_pagination_browser", "search_query_browser", "browser")
    use_api = engine_type == "api_json"

    kw_list = []
    if keywords and isinstance(keywords, list) and len(keywords) > 0:
        kw_list = keywords
    elif keyword:
        kw_list = [keyword]
    else:
        kw_list = [None]

    all_items = []
    last_result = None
    seen_hrefs = set()

    for kw in kw_list:
        next_url = None
        p = start_page
        while p <= max_pages:
            if use_api:
                items, result = _extract_one_page_api_json(config, p, base_url, config.get("api", {}))
            elif use_browser:
                items, result = _extract_one_page_browser(config, p, base_url, list_cfg, next_url)
            else:
                items, result = _extract_one_page(config, p, kw, base_url, list_cfg, next_url)
            last_result = result

            # Extract CSRF/token from first page
            if p == 1 and not use_api and not use_browser:
                url_tpl = list_cfg.get('url_template', '')
                if '{token}' in url_tpl:
                    token_re = list_cfg.get('token_regex', '')
                    if token_re and hasattr(result, 'text'):
                        tm = re.search(token_re, result.text)
                        if tm:
                            tkn = tm.group(1)
                            list_cfg['url_template'] = url_tpl.replace('{token}', tkn)
                            if 'url_template_first' in list_cfg:
                                list_cfg['url_template_first'] = list_cfg['url_template_first'].replace('{token}', tkn)

            if not items:
                break

            page_hrefs = {item["href"] for item in items}
            new_hrefs = page_hrefs - seen_hrefs
            if not new_hrefs:
                break
            seen_hrefs.update(new_hrefs)
            all_items.extend(items)

            if page_callback:
                try:
                    page_callback(items, p)
                except TypeError:
                    page_callback(items)

            if not use_api:
                detected = detect_next_page(
                    result._resp if hasattr(result, '_resp') and result._resp else result, config)
                if detected is None:
                    if list_cfg.get('url_template'):
                        next_url = None
                    else:
                        break
                if isinstance(detected, str):
                    current_url = getattr(result, 'url', base_url)
                    next_url = urljoin(current_url, detected)
                else:
                    next_url = None
            else:
                next_url = None

            p += 1

    return all_items, last_result


def detect_next_page(resp, config):
    """Detect 'next page' link. Returns href string, True, or None."""
    list_cfg = config.get("list", {})
    next_selector = list_cfg.get("next_page_selector", "")
    if not next_selector:
        next_selector = "a:contains('下一页'), a:contains('下页'), a:contains('后页'), a[rel='next']"
    elements = resp.css(next_selector)
    if elements:
        href = elements[0].attrib.get("href", "")
        if href and not href.startswith("javascript:"):
            return href
        return True
    return None


def classify_links(links, base_domain):
    """Classify links: WeChat / internal / external / attachment."""
    result = {"wechat": [], "internal": [], "external": [], "attachment": []}
    attachment_exts = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                       '.zip', '.rar', '.7z', '.txt', '.csv'}
    wechat_patterns = [
        r'mp\.weixin\.qq\.com/s/[A-Za-z0-9\-_]+',
        r'mp\.weixin\.qq\.com/s\?__biz=',
    ]

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
        is_wechat = False
        for pat in wechat_patterns:
            if re.search(pat, href):
                result["wechat"].append(link)
                is_wechat = True
                break
        if is_wechat:
            continue
        try:
            link_domain = urlparse(href).hostname or ""
        except Exception:
            link_domain = ""
        if not link_domain or link_domain == base_domain:
            result["internal"].append(link)
        elif _is_same_site_static(link_domain, base_domain):
            result["internal"].append(link)
        else:
            result["external"].append(link)
    return result


def _is_same_site_static(d1, d2):
    if not d1 or not d2:
        return False
    if d1 == d2:
        return True
    p1, p2 = d1.split("."), d2.split(".")
    if len(p1) >= 3 and len(p2) >= 3:
        if p1[-2] in ("gov", "com", "org", "net") and p1[-1] == "cn":
            return ".".join(p1[-3:]) == ".".join(p2[-3:])
        if p1[-1] in ("com", "cn", "org", "net"):
            return ".".join(p1[-2:]) == ".".join(p2[-2:])
    return False
