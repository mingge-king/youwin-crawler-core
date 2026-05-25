"""HTTP fetcher with retry, rate limiting, and circuit breaker."""
import time
import random
from urllib.parse import urlparse

from scrapling import Fetcher

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_domain_last_request = {}
_domain_errors = {}
_domain_circuit_breaker_until = {}
CIRCUIT_BREAKER_THRESHOLD = 5
CIRCUIT_BREAKER_COOLDOWN = 300
PERMANENT_BAN_THRESHOLD = 20
_permanent_ban = set()


class FetchResult:
    """Unified fetch response wrapper."""
    def __init__(self, url, status, size, text, headers, resp=None):
        self.url = url
        self.status = status
        self.size = size
        self.text = text
        self.headers = headers
        self._resp = resp

    @property
    def ok(self):
        return self.status == 200 and self.size > 2000

    def css(self, selector):
        return self._resp.css(selector) if self._resp else None


def fetch(url, method="GET", params=None, data=None, headers=None, timeout=30, rate_limit=1.0, retries=3, verify=True):
    """HTTP request with per-domain rate limiting, retry, and circuit breaker.

    Args:
        verify: SSL certificate verification (default True). Set False for broken-SSL gov sites."""
    domain = urlparse(url).hostname or ""
    dynamic_delay = rate_limit * (1 + _domain_errors.get(domain, 0) * 0.3)

    now = time.time()
    if domain in _domain_last_request:
        elapsed = now - _domain_last_request[domain]
        if elapsed < dynamic_delay:
            time.sleep(dynamic_delay - elapsed + random.uniform(0, 1))

    if domain in _permanent_ban:
        raise RuntimeError(f"Domain {domain} is permanently banned")

    if _domain_errors.get(domain, 0) >= CIRCUIT_BREAKER_THRESHOLD:
        cooldown_until = _domain_circuit_breaker_until.get(domain, 0)
        if time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time())
            raise RuntimeError(f"Circuit breaker tripped for {domain} ({_domain_errors[domain]} errors, recover in {remaining}s)")
        _domain_errors.pop(domain, None)
        _domain_circuit_breaker_until.pop(domain, None)

    default_headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if headers:
        default_headers.update(headers)

    last_error = None
    for attempt in range(retries):
        try:
            _domain_last_request[domain] = time.time()

            if method.upper() == "GET":
                resp = Fetcher.get(url, headers=default_headers, timeout=timeout, verify=verify)
            else:
                resp = Fetcher.post(url, headers=default_headers, data=data, timeout=timeout, verify=verify)

            status = resp.status if hasattr(resp, 'status') else 0
            text = _extract_text(resp)

            result = FetchResult(
                url=url, status=status, size=len(text), text=text,
                headers=resp.headers if hasattr(resp, 'headers') else {},
                resp=resp,
            )

            if result.ok:
                _domain_errors.pop(domain, None)
                _domain_circuit_breaker_until.pop(domain, None)
            else:
                if status == 429:
                    _domain_errors[domain] = _domain_errors.get(domain, 0) + 3
                elif status >= 500:
                    _domain_errors[domain] = _domain_errors.get(domain, 0) + 2
                else:
                    _domain_errors[domain] = _domain_errors.get(domain, 0) + 1
                if _domain_errors.get(domain, 0) >= PERMANENT_BAN_THRESHOLD:
                    _permanent_ban.add(domain)
                elif _domain_errors.get(domain, 0) >= CIRCUIT_BREAKER_THRESHOLD:
                    _domain_circuit_breaker_until[domain] = time.time() + CIRCUIT_BREAKER_COOLDOWN

            return result

        except Exception as e:
            last_error = e
            _domain_errors[domain] = _domain_errors.get(domain, 0) + 1
            if _domain_errors.get(domain, 0) >= PERMANENT_BAN_THRESHOLD:
                _permanent_ban.add(domain)
            elif _domain_errors.get(domain, 0) >= CIRCUIT_BREAKER_THRESHOLD:
                _domain_circuit_breaker_until[domain] = time.time() + CIRCUIT_BREAKER_COOLDOWN
            if attempt < retries - 1:
                time.sleep((2 ** attempt) * rate_limit)

    raise last_error if last_error else RuntimeError(f"Failed to fetch {url}")


def _extract_text(resp):
    """Extract text content from Scrapling Response."""
    if hasattr(resp, 'body') and resp.body:
        try:
            return resp.body.decode(resp.encoding if hasattr(resp, 'encoding') and resp.encoding else 'utf-8', errors='ignore')
        except Exception:
            pass
    if hasattr(resp, 'get_all_text'):
        try:
            t = resp.get_all_text()
            if t:
                return t
        except Exception:
            pass
    if hasattr(resp, 'text'):
        t = str(resp.text) if resp.text else ""
        if t:
            return t
    return ""
