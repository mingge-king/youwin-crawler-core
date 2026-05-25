"""Field-mapping-driven detail page extractor."""
from ggzy_crawler.fetcher import fetch
from ggzy_crawler.html_cleaner import clean_html


def extract_detail(url, field_map, config=None):
    """Extract structured data from a detail page using field mapping.

    field_map examples:
    [
        {"name": "title", "selector": "h1::text"},
        {"name": "date", "selector": ".info .date::text", "regex": r"\\d{4}-\\d{2}-\\d{2}"},
        {"name": "content", "selector": "#content::text"},
        {"name": "company", "selector": "td:contains('名称') + td::text"},
    ]
    """
    detail_cfg = (config or {}).get("detail", {})
    if detail_cfg.get("custom") and detail_cfg.get("_extractor"):
        return detail_cfg["_extractor"](url, field_map, config)

    result = fetch(url)
    if not result.ok:
        return {"_error": f"Fetch failed: status={result.status}", "_url": url}

    resp = result._resp
    data = {"_url": url, "_size": result.size}

    for field in field_map:
        name = field["name"]
        selector = field["selector"]
        try:
            if selector.endswith("::text") or "::text" in selector:
                values = resp.css(selector).getall()
                text = " ".join(str(v).strip() for v in values if str(v).strip())
            elif selector.endswith("::attr"):
                sel = selector[:-6]
                elements = resp.css(sel)
                text = elements[0].attrib.get(field.get("attr", ""), "") if elements else ""
            else:
                elements = resp.css(selector)
                text = str(elements[0].text or "").strip() if elements else ""

            if "regex" in field and text:
                import re
                m = re.search(field["regex"], text)
                if m:
                    text = m.group(1) if m.lastindex else m.group()

            data[name] = text
        except Exception as e:
            data[name] = f"EXTRACT_ERROR: {e}"

    data["content_html"] = clean_html(result.text, url=url)
    data["_resp"] = resp
    return data


def extract_table(resp, table_selector, column_map):
    """Extract structured data from HTML table, returns list of dicts."""
    rows = resp.css(f"{table_selector} tr")
    results = []
    for row in rows[1:]:
        cells = row.css("td")
        if not cells:
            continue
        record = {}
        for i, col in enumerate(column_map):
            if i < len(cells):
                record[col] = str(cells[i].text or "").strip()
        if record:
            results.append(record)
    return results
