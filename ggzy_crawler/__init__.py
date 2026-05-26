"""
ggzy-crawler-core: Self-bootstrapping crawler engine for large-scale web data collection.

Key features:
- Zero-config site auto-detection (15+ CMS types)
- WeChat official account article extraction
- Multi-engine list extraction (HTTP, Browser, API JSON)
- 6-level failure classification with automatic fallback
- Rule-driven, LLM-as-fallback architecture
- Per-site URL deduplication with disk persistence
"""

__version__ = "0.1.1"

from ggzy_crawler.fetcher import fetch, FetchResult
from ggzy_crawler.anti_bot import BrowserFetcher
from ggzy_crawler.html_cleaner import clean_html, html_to_markdown
from ggzy_crawler.cms_detector import quick_config, CMS_SIGNATURES
from ggzy_crawler.explorer import probe, explore, explore_search, detect_search_api, generate_strategy
from ggzy_crawler.wechat_handler import fetch_article, is_wechat_url, extract_wechat_urls
from ggzy_crawler.list_extractor import extract_list, extract_links, classify_links
from ggzy_crawler.detail_extractor import extract_detail
from ggzy_crawler.search_extractor import search, search_with_browser
from ggzy_crawler.convenience import crawl
from ggzy_crawler.dedup import (
    check_and_add,
    persist,
    load_from_disk,
    load_all_from_disk,
    size,
    skipped_count,
    stats,
)
