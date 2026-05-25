"""Example: Probe a site and crawl with intent — zero config.

Usage:
  python examples/probe_and_crawl.py https://example.gov.cn
  python examples/probe_and_crawl.py https://example.gov.cn "招标,中标,2025"
"""
import sys
from ggzy_crawler import crawl, probe, quick_config, extract_list


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.gov.cn"
    keywords = sys.argv[2].split(",") if len(sys.argv) > 2 else None

    print(f"Target: {url}")
    print(f"Looking for: {keywords or 'auto-detect (list page mode)'}")
    print()

    # One-shot: probe + config + crawl with intent
    result = crawl(url, keywords=keywords, max_pages=3)

    stats = result["stats"]
    print(f"Engine: {stats['engine']}")
    print(f"CMS: {stats.get('cms', 'N/A')}")
    print(f"Search available: {stats.get('has_search', False)}")
    print(f"Keywords used: {stats.get('keywords_used', [])}")
    print(f"Found: {stats['total_items']} items")
    print()

    for item in result["items"][:10]:
        print(f"  [{item['text'][:70]}]")
        print(f"   -> {item['href'][:90]}")
        print()

    if not result["items"]:
        print("No results. Try different keywords or check if the site is reachable.")


if __name__ == "__main__":
    main()
