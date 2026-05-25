"""Anti-bot engine: Playwright browser with anti-detection."""
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class BrowserFetcher:
    """Headless browser fetcher with optional stealth."""

    def __init__(self, headless=True, timeout=30000, channel=None):
        self.headless = headless
        self.timeout = timeout
        self.channel = channel  # None = default chromium, "msedge" = Edge
        self._playwright = None
        self._browser = None
        self._stealth = None

    def start(self):
        self._playwright = sync_playwright().start()
        launch_args = {"headless": self.headless}
        if self.channel:
            launch_args["channel"] = self.channel
        self._browser = self._playwright.chromium.launch(**launch_args)
        try:
            from playwright_stealth import Stealth
            self._stealth = Stealth()
        except ImportError:
            self._stealth = None

    def _new_page(self):
        page = self._browser.new_page()
        if self._stealth:
            self._stealth.use_sync(page)
        return page

    def stop(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    def fetch(self, url, wait_for_selector=None, wait_ms=2000):
        page = self._new_page()
        try:
            page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=self.timeout)
            elif wait_ms:
                page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            page.close()

    def search_and_get_results(self, url, input_selector, keyword,
                               submit_selector=None, result_selector=None, wait_ms=3000):
        page = self._new_page()
        try:
            page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            page.fill(input_selector, keyword)
            if submit_selector:
                page.click(submit_selector)
            else:
                page.press(input_selector, "Enter")
            if result_selector:
                page.wait_for_selector(result_selector, timeout=self.timeout)
            elif wait_ms:
                page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            page.close()

    def execute_actions(self, url, actions, wait_ms=3000):
        """Generic interaction engine: open page -> action sequence -> return HTML.

        actions format: [
            {"type": "fill", "selector": "input[name='q']", "value": "2025"},
            {"type": "press", "selector": "input[name='q']", "key": "Enter"},
            {"type": "click", "selector": "button.submit"},
            {"type": "wait", "ms": 5000},
            {"type": "wait_for_selector", "selector": ".results", "timeout": 10000},
            {"type": "scroll", "pixels": 1000},
            {"type": "goto", "url": "https://..."},
            {"type": "click_text", "text": "跳转"},
        ]
        """
        page = self._new_page()
        try:
            page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            if wait_ms:
                page.wait_for_timeout(wait_ms)

            for action in actions:
                atype = action.get("type", "")
                selector = action.get("selector", "")

                if atype == "fill":
                    page.fill(selector, str(action.get("value", "")))
                elif atype == "press":
                    page.press(selector, action.get("key", "Enter"))
                elif atype == "click":
                    page.click(selector)
                elif atype == "click_text":
                    page.click(f"text={action.get('text', '')}")
                elif atype == "wait":
                    page.wait_for_timeout(action.get("ms", 1000))
                elif atype == "wait_for_selector":
                    sel = action.get("selector", "")
                    to = action.get("timeout", self.timeout)
                    page.wait_for_selector(sel, timeout=to)
                elif atype == "scroll":
                    pixels = action.get("pixels", 500)
                    page.evaluate(f"window.scrollBy(0, {pixels})")
                elif atype == "goto":
                    page.goto(action.get("url", url),
                              timeout=action.get("timeout", self.timeout),
                              wait_until="domcontentloaded")

            return page.content()
        finally:
            page.close()
