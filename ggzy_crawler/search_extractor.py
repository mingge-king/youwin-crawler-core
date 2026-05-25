"""Search-query engine: form submission + result list parsing."""
from ggzy_crawler.fetcher import fetch
from ggzy_crawler.list_extractor import extract_links


def search(config, keyword, page=1):
    """Execute search and return results list.

    config.search example:
    {
        "url": "/search/",
        "method": "GET",
        "params": {"keywords": "{keyword}", "page": "{page}"},
        "result_item_selector": "div.search-item",
        "result_link_selector": "a[href]",
    }
    """
    base_url = config["base_url"]
    search_cfg = config["search"]

    url = base_url.rstrip("/") + "/" + search_cfg["url"].lstrip("/")
    method = search_cfg.get("method", "GET").upper()

    param_map = {}
    for k, v in search_cfg.get("params", {}).items():
        param_map[k] = str(v).replace("{keyword}", keyword).replace("{page}", str(page))

    params = param_map if method == "GET" else None
    data = param_map if method != "GET" else None

    result = fetch(url, method=method, params=params, data=data)
    if not result.ok:
        return [], result

    item_selector = search_cfg.get("result_item_selector", "a[href]")
    link_selector = search_cfg.get("result_link_selector")
    items = extract_links(result, item_selector, link_selector, base_url)

    return items, result


def search_with_browser(browser, config, keyword, page=1):
    """Execute search using Playwright browser (for JS-rendered sites).

    config.search example:
    {
        "url": "/search/",
        "input_selector": "input[name='keywords']",
        "submit_selector": "button[type='submit']",
        "result_item_selector": "div.search-item a",
        "wait_ms": 3000,
    }
    """
    base_url = config["base_url"]
    search_cfg = config["search"]

    url = base_url.rstrip("/") + "/" + search_cfg["url"].lstrip("/")

    html = browser.search_and_get_results(
        url=url,
        input_selector=search_cfg["input_selector"],
        keyword=keyword,
        submit_selector=search_cfg.get("submit_selector"),
        result_selector=search_cfg.get("result_item_selector"),
        wait_ms=search_cfg.get("wait_ms", 3000),
    )

    from scrapling import Selector
    resp = Selector(html)

    item_selector = search_cfg.get("result_item_selector", "a[href]")
    items = extract_links(resp, item_selector, search_cfg.get("result_link_selector"), base_url)

    return items, html
