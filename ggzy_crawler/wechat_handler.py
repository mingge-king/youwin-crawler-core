"""WeChat Official Account article extractor — pure rules, no LLM.

Pipeline:
  Short link (mp.weixin.qq.com/s/xxx)
    -> Browser open
    -> Detect "migrated" page -> click jump button
    -> Long link (mp.weixin.qq.com/s?__biz=...)
    -> Extract title + content + publish date
"""
import re
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


# ── Page type detection patterns ──

MIGRATED_PAGE_INDICATORS = [
    (r'页面.?已.?迁移', 10),
    (r'已迁移', 10),
    (r'该公众号已迁移', 8),
    (r'账号已迁移', 8),
    (r'WeChat Official Account.*moved', 6),
]

MIGRATED_BUTTON_SELECTORS = [
    ".weui-msg__opr-area a", ".weui-btn",
    "a[href*='__biz=']", "a[href*='mp.weixin.qq.com/s?']",
    ".migration-message a",
    "button:has-text('访问')", "button:has-text('继续')",
    "a:has-text('访问')", "a:has-text('跳转')",
    "a:has-text('继续访问')", "a:has-text('点击')",
]

ARTICLE_CONTENT_SELECTORS = [
    "#js_content", ".rich_media_content", "#page-content",
    ".weui-article", "article",
]

TITLE_SELECTORS = [
    "#activity-name", ".rich_media_title", "#js_article_title",
    "h1.title", "h1", "title::text",
]

DATE_SELECTORS = [
    "#publish_time", "#post-date", ".rich_media_meta_text",
    ".weui-msg__time", "time",
]


class WechatArticle:
    """Extracted WeChat article content."""
    def __init__(self):
        self.url = ""
        self.final_url = ""
        self.title = ""
        self.content_text = ""
        self.content_html = ""
        self.publish_time = ""
        self.author = ""
        self.is_migrated = False
        self.error = ""


def fetch_article(url, headless=True, timeout=30000, channel=None):
    """Fetch WeChat article with automatic migration-page handling.

    Args:
        url: mp.weixin.qq.com/s/xxx or ?__biz=... format
        headless: headless browser mode
        timeout: page load timeout (ms)
        channel: browser channel (None=chromium, "msedge"=Edge)

    Returns:
        WechatArticle
    """
    article = WechatArticle()
    article.url = url

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
            page.wait_for_timeout(5000)
        except Exception as e:
            article.error = f"Page load failed: {e}"
            browser.close()
            return article

        current_url = page.url
        article.final_url = current_url
        content = page.content()

        if _detect_migrated_page(content):
            article.is_migrated = True
            if _click_migrate_button(page):
                page.wait_for_timeout(4000)
                article.final_url = page.url
                content = page.content()

        article.title = _extract_title(page, content)
        article.content_text = _extract_content_text(page, content)
        article.content_html = _extract_content_html(page)
        article.publish_time = _extract_date(page, content)
        article.author = _extract_author(page, content)

        browser.close()

    return article


def _detect_migrated_page(html):
    for pattern, _ in MIGRATED_PAGE_INDICATORS:
        if re.search(pattern, html, re.IGNORECASE):
            return True
    return False


def _click_migrate_button(page):
    for selector in MIGRATED_BUTTON_SELECTORS:
        try:
            el = page.query_selector(selector)
            if el:
                href = el.get_attribute("href") or ""
                text = (el.inner_text() or "").strip()
                if text and any(kw in text for kw in ["投诉", "举报", "取消", "返回"]):
                    continue
                if "__biz=" in href:
                    page.goto(href, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    return True
                el.click()
                page.wait_for_timeout(4000)
                return True
        except Exception:
            continue
    return False


def _extract_title(page, html):
    for sel in TITLE_SELECTORS:
        try:
            if sel.endswith("::text"):
                css = sel.replace("::text", "")
                el = page.query_selector(css)
                if el:
                    text = (el.inner_text() or "").strip()
                    if text and len(text) > 2:
                        return text[:500]
            else:
                el = page.query_selector(sel)
                if el:
                    text = (el.inner_text() or "").strip()
                    if text and len(text) > 2:
                        return text[:500]
        except Exception:
            continue
    m = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:500]
    return ""


def _extract_content_text(page, html):
    for sel in ARTICLE_CONTENT_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.inner_text() or "").strip()
                if len(text) > 100:
                    return text
        except Exception:
            continue
    try:
        text = page.evaluate("""() => {
            const sel = document.querySelector('#js_content');
            if (sel) return sel.innerText || '';
            const art = document.querySelector('.rich_media_content');
            if (art) return art.innerText || '';
            const body = document.querySelector('body');
            return body ? body.innerText : '';
        }""")
        if text and len(text.strip()) > 100:
            return text.strip()
    except Exception:
        pass
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
    if body_match:
        text = re.sub(r'<script[^>]*>.*?</script>', '', body_match.group(1), flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    return ""


def _extract_content_html(page):
    for sel in ARTICLE_CONTENT_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                html = el.inner_html() or ""
                if len(html) > 200:
                    return html
        except Exception:
            continue
    try:
        html = page.evaluate("""() => {
            const el = document.querySelector('#js_content') || document.querySelector('.rich_media_content');
            return el ? el.innerHTML : '';
        }""")
        if html:
            return html
    except Exception:
        pass
    return ""


def _extract_date(page, html):
    for sel in DATE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.inner_text() or el.text_content() or "").strip()
                m = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)', text)
                if m:
                    return m.group(1)
                if re.match(r'\d{4}-\d{2}-\d{2}', text):
                    return text[:10]
        except Exception:
            continue
    return ""


def _extract_author(page, html):
    try:
        el = page.query_selector("#js_name, .rich_media_meta_nickname, #js_wx_follow_nickname")
        if el:
            return (el.inner_text() or "").strip()[:200]
    except Exception:
        pass
    m = re.search(r'og:article:author["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if m:
        return m.group(1)[:200]
    return ""


def fetch_articles(urls, headless=True, timeout=30000):
    """Batch fetch WeChat articles (serial, avoids rate-limiting)."""
    for i, url in enumerate(urls):
        if i > 0:
            time.sleep(2)
        yield fetch_article(url, headless=headless, timeout=timeout)


def is_wechat_url(url):
    """Check if URL is a WeChat Official Account link."""
    return bool(re.search(r'mp\.weixin\.qq\.com/s/[A-Za-z0-9\-_]+', url) or
                re.search(r'mp\.weixin\.qq\.com/s\?__biz=', url))


def extract_wechat_urls(text):
    """Extract all WeChat URLs from text."""
    urls = set()
    for pat in [r'mp\.weixin\.qq\.com/s/[A-Za-z0-9\-_]+', r'mp\.weixin\.qq\.com/s\?__biz=[^"\'\s]+']:
        for m in re.finditer(pat, text):
            urls.add(m.group(0))
    return sorted(urls)
