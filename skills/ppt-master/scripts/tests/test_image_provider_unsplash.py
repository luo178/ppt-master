"""Regression tests for the Unsplash image-search provider."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import image_search  # noqa: E402
from image_sources import provider_unsplash  # noqa: E402
from image_sources.provider_common import (  # noqa: E402
    LICENSE_TIER_NO_ATTRIBUTION,
    ImageSearchRequest,
)


def _photo(
    *,
    photo_id: str = "abc123",
    width: int = 4000,
    height: int = 3000,
    raw: str = "https://images.unsplash.com/photo-1?ixid=x",
    author: str = "Jane Doe",
    alt: str = "data center aisle",
) -> dict:
    return {
        "id": photo_id,
        "width": width,
        "height": height,
        "alt_description": alt,
        "description": None,
        "urls": {
            "raw": raw,
            "full": "https://images.unsplash.com/photo-1?fm=jpg",
            "regular": "https://images.unsplash.com/photo-1?w=1080",
            "small": "https://images.unsplash.com/photo-1?w=400",
        },
        "links": {
            "html": "https://unsplash.com/photos/abc123",
            "download_location": "https://api.unsplash.com/photos/abc123/download",
        },
        "user": {"name": author, "username": "jane"},
    }


class ParseResultsTests(unittest.TestCase):
    def test_maps_photo_fields_to_candidate(self) -> None:
        # Arrange
        payload = {"results": [_photo()]}

        # Act
        candidates = provider_unsplash.parse_results(payload)

        # Assert
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.provider, "unsplash")
        self.assertEqual(candidate.asset_id, "abc123")
        self.assertEqual(candidate.title, "data center aisle")
        self.assertEqual(candidate.author, "Jane Doe")
        self.assertEqual(candidate.source_page_url, "https://unsplash.com/photos/abc123")
        self.assertEqual(candidate.license_name, "Unsplash License")
        self.assertEqual(candidate.license_tier, LICENSE_TIER_NO_ATTRIBUTION)
        self.assertEqual((candidate.width, candidate.height), (4000, 3000))
        self.assertEqual(candidate.preview_url, "https://images.unsplash.com/photo-1?w=400")

    def test_download_url_requests_a_deck_sized_rendition(self) -> None:
        # Arrange
        payload = {"results": [_photo()]}

        # Act
        candidate = provider_unsplash.parse_results(payload)[0]

        # Assert — imgix parameters are appended, existing query preserved
        self.assertTrue(candidate.download_url.startswith("https://images.unsplash.com/photo-1?ixid=x"))
        self.assertIn("w=2560", candidate.download_url)
        self.assertIn("fm=jpg", candidate.download_url)

    def test_falls_back_to_full_url_without_raw(self) -> None:
        # Arrange
        photo = _photo(raw="")
        photo["urls"]["raw"] = ""

        # Act
        candidate = provider_unsplash.parse_results({"results": [photo]})[0]

        # Assert
        self.assertEqual(candidate.download_url, "https://images.unsplash.com/photo-1?fm=jpg")

    def test_skips_entries_without_any_download_url(self) -> None:
        # Arrange
        photo = _photo()
        photo["urls"] = {}

        # Act
        candidates = provider_unsplash.parse_results({"results": [photo]})

        # Assert
        self.assertEqual(candidates, [])


class SearchTests(unittest.TestCase):
    def test_requires_access_key(self) -> None:
        # Arrange
        request = ImageSearchRequest(query="data center")

        # Act / Assert
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                provider_unsplash.search(request)
        self.assertIn("UNSPLASH_ACCESS_KEY", str(ctx.exception))

    def test_sends_client_id_header_and_orientation(self) -> None:
        # Arrange
        request = ImageSearchRequest(query="data center", orientation="landscape")
        response = MagicMock()
        response.json.return_value = {"results": [_photo()]}

        # Act
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "key-123"}, clear=True):
            with patch.object(provider_unsplash.requests, "get", return_value=response) as get:
                candidates = provider_unsplash.search(request)

        # Assert
        self.assertEqual(len(candidates), 1)
        kwargs = get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Client-ID key-123")
        self.assertEqual(kwargs["params"]["orientation"], "landscape")
        self.assertEqual(kwargs["params"]["content_filter"], "high")

    def test_keeps_trying_simplified_queries_until_results(self) -> None:
        # Arrange
        request = ImageSearchRequest(query="data center server room aisle")
        empty = MagicMock()
        empty.json.return_value = {"results": []}
        hit = MagicMock()
        hit.json.return_value = {"results": [_photo()]}

        # Act
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "key-123"}, clear=True):
            with patch.object(
                provider_unsplash.requests, "get", side_effect=[empty, hit]
            ) as get:
                candidates = provider_unsplash.search(request)

        # Assert — the second attempt uses a shortened query
        self.assertEqual(len(candidates), 1)
        self.assertGreaterEqual(get.call_count, 2)
        first_query = get.call_args_list[0].kwargs["params"]["query"]
        second_query = get.call_args_list[1].kwargs["params"]["query"]
        self.assertNotEqual(first_query, second_query)


class NotifyDownloadTests(unittest.TestCase):
    def test_pings_download_location_for_unsplash_candidate(self) -> None:
        # Arrange
        candidate = provider_unsplash.parse_results({"results": [_photo()]})[0]

        # Act
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "key-123"}, clear=True):
            with patch.object(provider_unsplash.requests, "get") as get:
                provider_unsplash.notify_download(candidate)

        # Assert
        self.assertEqual(get.call_count, 1)
        self.assertTrue(get.call_args.args[0].endswith("/photos/abc123/download"))

    def test_ignores_non_unsplash_candidate(self) -> None:
        # Arrange
        candidate = provider_unsplash.parse_results({"results": [_photo()]})[0]
        candidate.provider = "pixabay"

        # Act
        with patch.object(provider_unsplash.requests, "get") as get:
            provider_unsplash.notify_download(candidate)

        # Assert
        get.assert_not_called()

    def test_swallows_network_errors(self) -> None:
        # Arrange
        candidate = provider_unsplash.parse_results({"results": [_photo()]})[0]

        # Act / Assert — no exception escapes
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "key-123"}, clear=True):
            with patch.object(
                provider_unsplash.requests, "get", side_effect=OSError("boom")
            ):
                provider_unsplash.notify_download(candidate)


class DispatcherIntegrationTests(unittest.TestCase):
    def test_provider_is_registered_as_keyed(self) -> None:
        self.assertIn("unsplash", image_search.PROVIDER_MODULES)
        self.assertIn("unsplash", image_search.KEYED_PROVIDERS)
        self.assertIn("unsplash", image_search.ALL_PROVIDERS)

    def test_default_chain_appends_unsplash_when_keyed(self) -> None:
        # Arrange / Act
        with patch.dict("os.environ", {"UNSPLASH_ACCESS_KEY": "key-123"}, clear=True):
            chain = image_search._default_provider_chain()

        # Assert
        self.assertIn("unsplash", chain)
        self.assertLess(
            chain.index("unsplash"), chain.index("openverse")
        )

    def test_missing_key_is_a_skippable_keyed_provider(self) -> None:
        # Arrange
        exc = RuntimeError("UNSPLASH_ACCESS_KEY is not set.")

        # Act
        skippable = image_search._is_keyed_provider_unconfigured("unsplash", exc)

        # Assert
        self.assertTrue(skippable)

    def test_env_loader_reads_unsplash_prefix(self) -> None:
        # Act
        with patch.object(image_search, "load_prefixed_env_file") as loader:
            image_search._load_search_env_file()

        # Assert
        prefixes = loader.call_args.args[0]
        self.assertIn("UNSPLASH_", prefixes)
        self.assertIn("PIXABAY_", prefixes)


if __name__ == "__main__":
    unittest.main()
