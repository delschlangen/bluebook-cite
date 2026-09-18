"""Tests for the outbound-fetch guard.

The citation tools fetch URLs supplied by anonymous visitors. Without these
checks that is a server-side request forgery primitive against the container's
own network.
"""

import httpx
import pytest
import respx

from app.models.citation import Citation, CitationStatus, CitationType
from app.services.lookup_service import LegalLookupService
from app.utils.safe_fetch import (
    MAX_RESPONSE_BYTES,
    UnsafeURLError,
    assert_safe_url,
    safe_get,
)

BLOCKED_URLS = [
    # Cloud instance metadata: the classic SSRF target.
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    # Loopback.
    "http://127.0.0.1:8000/health",
    "http://localhost:8000/health",
    "http://[::1]:8000/",
    # Private ranges.
    "http://10.0.0.5/",
    "http://192.168.1.1/admin",
    "http://172.16.0.1/",
    # Unspecified and link-local.
    "http://0.0.0.0/",
    "http://169.254.1.1/",
]

BLOCKED_SCHEMES = [
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_INFO",
    "ftp://internal.example.com/",
    "data:text/html,<script>alert(1)</script>",
]


@pytest.mark.parametrize("url", BLOCKED_URLS, ids=[u[:44] for u in BLOCKED_URLS])
def test_internal_addresses_are_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", BLOCKED_SCHEMES, ids=[u[:28] for u in BLOCKED_SCHEMES])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", ["", "   ", "not a url", "http://", "https:///path"])
def test_malformed_input_is_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_dotted_internal_suffix_is_refused():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://anything.internal/secrets")


def test_ordinary_public_url_is_allowed():
    url = "https://www.courtlistener.com/opinion/1/test/"
    assert assert_safe_url(url) == url


@pytest.mark.asyncio
class TestSafeGet:
    @respx.mock
    async def test_redirect_into_a_private_address_is_refused(self):
        """httpx's follow_redirects would chase this without re-checking.
        Following manually and re-validating each hop is the point."""
        respx.get("https://evil.example.com/start").mock(
            return_value=httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://evil.example.com/start")

    @respx.mock
    async def test_redirect_to_loopback_is_refused(self):
        respx.get("https://evil.example.com/start").mock(
            return_value=httpx.Response(301, headers={"location": "http://127.0.0.1/admin"})
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://evil.example.com/start")

    @respx.mock
    async def test_redirect_chain_is_bounded(self):
        respx.get("https://loop.example.com/a").mock(
            return_value=httpx.Response(302, headers={"location": "https://loop.example.com/a"})
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://loop.example.com/a")

    @respx.mock
    async def test_oversized_response_is_refused(self):
        respx.get("https://big.example.com/page").mock(
            return_value=httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://big.example.com/page")

    @respx.mock
    async def test_ordinary_page_is_fetched(self):
        respx.get("https://example.com/article").mock(
            return_value=httpx.Response(200, html="<title>An Article</title>")
        )
        async with httpx.AsyncClient() as client:
            response = await safe_get(client, "https://example.com/article")
        assert response.status_code == 200
        assert "An Article" in response.text


@pytest.mark.asyncio
class TestLookupWebsiteIsGuarded:
    async def test_metadata_url_is_blocked_end_to_end(self):
        """The reachable path: a visitor pastes a URL, the extractor makes it a
        website citation, and lookup_website fetches it."""
        citation = Citation(
            type=CitationType.WEBSITE,
            status=CitationStatus.INCOMPLETE,
            raw_text="http://169.254.169.254/latest/meta-data/",
            position_start=0,
            position_end=40,
            url="http://169.254.169.254/latest/meta-data/",
        )
        service = LegalLookupService()
        try:
            result = await service.lookup_website(citation)
        finally:
            await service.close()

        assert result["found"] is False
        assert result.get("blocked") is True

    async def test_loopback_url_is_blocked_end_to_end(self):
        citation = Citation(
            type=CitationType.WEBSITE,
            status=CitationStatus.INCOMPLETE,
            raw_text="http://localhost:8000/health",
            position_start=0,
            position_end=28,
            url="http://localhost:8000/health",
        )
        service = LegalLookupService()
        try:
            result = await service.lookup_website(citation)
        finally:
            await service.close()

        assert result["found"] is False
        assert result.get("blocked") is True
