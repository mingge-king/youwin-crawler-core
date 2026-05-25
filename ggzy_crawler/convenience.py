"""Convenience API: one-shot crawl with intent."""

from ggzy_crawler.explorer import probe as _probe, DEFAULT_KEYWORDS
from ggzy_crawler.cms_detector import quick_config as _quick_config
from ggzy_crawler.list_extractor import extract_list as _extract_list


def crawl(url, keywords=None, date_from=None, date_to=None,
          max_pages=10, headless=True, channel=None):
    """One-shot crawl: probe site, generate config, extract matching items.

    Args:
        url: site homepage URL
        keywords: list of keywords to search for (e.g. ["招标", "中标", "2025"]).
                  If None and site has search, uses default annual keywords.
                  If None and site has no search, crawls the list page as-is.
        date_from: optional start date filter (YYYY-MM-DD)
        date_to: optional end date filter (YYYY-MM-DD)
        max_pages: max pages to crawl per keyword
        headless: headless browser mode
        channel: browser channel (None=chromium, "msedge"=Edge)

    Returns:
        dict with keys: items, config, probe, stats

    Example:
        >>> result = crawl("https://example.gov.cn", keywords=["招标", "中标"])
        >>> print(result["stats"])
        {'total_items': 234, 'pages_crawled': 5, 'engine': 'search_query'}
        >>> for item in result["items"][:3]:
        ...     print(item["text"], item["href"])
    """
    # Step 1: probe site
    pr = _probe(url, headless=headless, timeout=30000, channel=channel)
    if pr.error:
        return {"items": [], "config": None, "probe": pr, "stats": {"error": pr.error}}

    # Step 2: generate config
    site_name = pr.domain or url
    config = _quick_config(url, site_name)

    # Step 3: determine engine & keywords
    kw_list = keywords
    if not kw_list and pr.has_search:
        kw_list = DEFAULT_KEYWORDS[:4]  # ["2025", "2024", "2023", "招标"]

    # Override max_pages
    if "list" in config:
        config["list"]["max_pages"] = max_pages

    # Step 4: extract
    if kw_list and pr.has_search:
        # Use search_query engine for keyword-driven crawl
        search_cfg = {}
        if pr.search_inputs:
            best = pr.search_inputs[0]
            search_cfg = {
                "input_selector": best["selector"],
                "input_name": best.get("name", ""),
                "form_action": pr.search_form_action or "",
            }
        config["search"] = search_cfg
        config["engine"] = "search_query"

    items, last_result = _extract_list(config, page=1, keywords=kw_list)

    # Step 5: stats
    stats = {
        "total_items": len(items),
        "pages_crawled": max_pages,
        "engine": config.get("engine", "unknown"),
        "cms": pr.cms_signature,
        "has_search": pr.has_search,
        "keywords_used": kw_list,
    }

    return {"items": items, "config": config, "probe": pr, "stats": stats}
