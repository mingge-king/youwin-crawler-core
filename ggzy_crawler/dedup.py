"""
Per-site URL deduplication with disk persistence.

Provides a thread-safe in-memory set per site_code, backed by _urls.txt on disk
so dedup state survives restarts. Same-site duplicates are blocked; different-site
duplicates are preserved for cross-validation.
"""
import os
import threading

# {site_code: set(url)}
_index: dict[str, set] = {}
_lock = threading.Lock()

_skipped_count = 0


def check_and_add(site_code: str, url: str) -> bool:
    """Return True if URL is new for this site_code (and record it). False if duplicate."""
    global _skipped_count
    url_clean = url.rstrip("/").lower()
    if not url_clean:
        return True
    with _lock:
        if site_code not in _index:
            _index[site_code] = set()
        if url_clean in _index[site_code]:
            _skipped_count += 1
            return False
        _index[site_code].add(url_clean)
        return True


def persist(site_code: str, url: str, base_dir: str) -> None:
    """Append one URL to the site's _urls.txt file."""
    url_clean = url.rstrip("/").lower()
    if not url_clean:
        return
    site_dir = os.path.join(base_dir, site_code)
    os.makedirs(site_dir, exist_ok=True)
    try:
        with open(os.path.join(site_dir, "_urls.txt"), "a", encoding="utf-8") as f:
            f.write(url_clean + "\n")
    except Exception:
        pass


def load_from_disk(site_code: str, base_dir: str) -> int:
    """Restore URL index for one site from _urls.txt. Returns count loaded."""
    uf = os.path.join(base_dir, site_code, "_urls.txt")
    if not os.path.exists(uf):
        return 0
    try:
        with open(uf, "r", encoding="utf-8") as f:
            urls = {line.strip() for line in f if line.strip()}
        with _lock:
            _index[site_code] = urls
        return len(urls)
    except Exception:
        return 0


def load_all_from_disk(base_dir: str) -> dict[str, int]:
    """Scan base_dir for _urls.txt files and restore all. Returns {site_code: count}."""
    if not os.path.isdir(base_dir):
        return {}
    restored = {}
    for site in os.listdir(base_dir):
        cnt = load_from_disk(site, base_dir)
        if cnt:
            restored[site] = cnt
    return restored


def size(site_code: str | None = None) -> int:
    """Return number of URLs tracked. If site_code is None, return total across all sites."""
    with _lock:
        if site_code is not None:
            return len(_index.get(site_code, set()))
        return sum(len(v) for v in _index.values())


def skipped_count() -> int:
    """Total number of duplicates skipped since startup."""
    return _skipped_count


def stats() -> dict:
    """Return {total_urls, site_count, skipped_dups}."""
    with _lock:
        return {
            "total_urls": sum(len(v) for v in _index.values()),
            "site_count": len(_index),
            "skipped_dups": _skipped_count,
        }
