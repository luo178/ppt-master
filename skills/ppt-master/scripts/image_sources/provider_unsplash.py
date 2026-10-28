"""Unsplash provider.

Requires ``UNSPLASH_ACCESS_KEY`` in the environment. The Unsplash License
allows commercial use without attribution, so all returned candidates are
classified as ``no-attribution``.

The API guidelines ask clients to hit an image's ``download_location`` when
the file is actually saved; ``image_search.py`` calls :func:`notify_download`
on a best-effort basis after a successful download.

API docs: https://unsplash.com/documentation
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from console_encoding import configure_utf8_stdio  # noqa: E402

configure_utf8_stdio()

if __name__ == "__main__":
    print(__doc__)
    print("Use via: python3 skills/ppt-master/scripts/image_search.py ...")
    raise SystemExit(0 if any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]) else 1)

import os

import requests

from image_sources.provider_common import (
    AssetCandidate,
    ImageSearchRequest,
    LICENSE_TIER_NO_ATTRIBUTION,
    USER_AGENT,
    build_query_progression,
    normalize_license_name,
)


API_URL = "https://api.unsplash.com/search/photos"
DEFAULT_PAGE_SIZE = 20
DEFAULT_TIMEOUT = 30
DOWNLOAD_NOTIFY_TIMEOUT = 10
# The demo tier allows 50 requests/hour, so ask for the largest supported page
# only when the caller does; image_search.py defaults to a small page.
MAX_PAGE_SIZE = 30

_HEADERS_VERSION = {"Accept-Version": "v1"}

_ORIENTATION_MAP = {
    "landscape": "landscape",
    "portrait": "portrait",
    "square": "squarish",
}

# ``urls.raw`` is an imgix URL; these parameters deliver a deck-sized JPEG
# instead of the untouched camera original.
_RAW_PARAMS = "w=2560&q=90&fm=jpg"


def _require_api_key() -> str:
    key = (os.environ.get("UNSPLASH_ACCESS_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "UNSPLASH_ACCESS_KEY is not set. Add it to your environment or .env file. "
            "Get one at https://unsplash.com/developers"
        )
    return key


def _download_url(urls: dict) -> str:
    """Prefer a 2560px-wide rendition of ``urls.raw``."""
    raw = (urls.get("raw") or "").strip()
    if raw:
        separator = "&" if "?" in raw else "?"
        return f"{raw}{separator}{_RAW_PARAMS}"
    return (urls.get("full") or urls.get("regular") or "").strip()


def parse_results(payload: dict) -> list[AssetCandidate]:
    """Translate an Unsplash response into candidates."""
    candidates: list[AssetCandidate] = []
    for item in payload.get("results", []) or []:
        urls = item.get("urls") or {}
        download_url = _download_url(urls)
        if not download_url:
            continue

        links = item.get("links") or {}
        author = (item.get("user") or {}).get("name") or ""
        title = (
            (item.get("alt_description") or "").strip()
            or (item.get("description") or "").strip()
            or "Unsplash photo"
        )

        candidates.append(
            AssetCandidate(
                provider="unsplash",
                title=title,
                asset_id=str(item.get("id") or ""),
                source_page_url=(links.get("html") or "").strip(),
                license_name=normalize_license_name("Unsplash License"),
                license_url="https://unsplash.com/license",
                license_tier=LICENSE_TIER_NO_ATTRIBUTION,
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                download_url=download_url,
                preview_url=(
                    urls.get("small") or urls.get("thumb") or ""
                ).strip(),
                author=author.strip(),
                raw=item,
            )
        )
    return candidates


def search(
    request: ImageSearchRequest,
    *,
    license_tier_filter: str = "no-attribution-only",
    page_size: int = DEFAULT_PAGE_SIZE,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[AssetCandidate]:
    """Search Unsplash for candidates.

    Unsplash images are uniformly ``no-attribution``, so the ``"all"`` filter
    behaves identically to ``"no-attribution-only"``. Both are accepted to
    keep the dispatcher simple.
    """
    if license_tier_filter not in {"no-attribution-only", "all"}:
        raise ValueError(f"unsupported license_tier_filter: {license_tier_filter!r}")

    api_key = _require_api_key()
    orientation = (request.orientation or "").strip().lower()

    for query in build_query_progression(request.query):
        params: dict[str, str | int] = {
            "query": query,
            "per_page": min(page_size, MAX_PAGE_SIZE),
            "content_filter": "high",
        }
        if orientation in _ORIENTATION_MAP:
            params["orientation"] = _ORIENTATION_MAP[orientation]

        response = requests.get(
            API_URL,
            params=params,
            headers={
                "Authorization": f"Client-ID {api_key}",
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                **_HEADERS_VERSION,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        candidates = parse_results(response.json())
        if candidates:
            return candidates

    return []


def notify_download(candidate: AssetCandidate, *, timeout: int = DOWNLOAD_NOTIFY_TIMEOUT) -> None:
    """Trigger the Unsplash download counter for a saved asset.

    Best effort by contract: the API guidelines require the ping, but a failed
    notification must never fail the download that already succeeded.
    """
    if candidate.provider != "unsplash":
        return
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    location = ((raw.get("links") or {}).get("download_location") or "").strip()
    if not location:
        return
    try:
        with requests.get(
            location,
            headers={
                "Authorization": f"Client-ID {_require_api_key()}",
                "User-Agent": USER_AGENT,
                **_HEADERS_VERSION,
            },
            timeout=timeout,
            stream=True,
        ) as response:
            response.close()
    except Exception:
        return
