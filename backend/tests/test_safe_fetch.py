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

PUBLIC_IP = "93.184.216.34"

# Names the tests use, and what each resolves to. Resolution is faked so the suite
# never touches DNS. Without this the redirect tests "passed" whenever the
# starting hostname failed to resolve, because that raises the same error the
# redirect check raises, so they proved nothing about redirects.
FAKE_DNS = {
    "localhost": ["127.0.0.1"],
    "internal.example.com": ["10.0.0.5"],
    "loopback.example.com": ["127.0.0.1"],
    "metadata.example.com": ["169.254.169.254"],
    "rebind.example.com": [PUBLIC_IP, "10.0.0.5"],  # one public, one private
    "v6loop.example.com": ["::1"],
}


@pytest.fixture(autouse=True)
def hermetic_dns(monkeypatch):
    import socket

    def fake_getaddrinfo(host, port, *args, **kwargs):
        addresses = FAKE_DNS.get(host, [PUBLIC_IP])
        family = {True: socket.AF_INET6, False: socket.AF_INET}
        return [
            (family[":" in addr], socket.SOCK_STREAM, 6, "", (addr, port or 0))
            for addr in addresses
        ]

    monkeypatch.setattr("app.utils.safe_fetch.socket.getaddrinfo", fake_getaddrinfo)


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


# A PUBLIC host with a non-HTTP scheme. The URLs above are also refused for other
# reasons (no host, loopback address), so they cannot show that the scheme check
# itself works. These can: nothing else is wrong with them.
PUBLIC_HOST_BAD_SCHEMES = [
    "ftp://example.com/file",
    "gopher://example.com/",
    "file://example.com/etc/passwd",
    "ldap://example.com/",
    "dict://example.com:11211/stat",
]


@pytest.mark.parametrize("url", PUBLIC_HOST_BAD_SCHEMES)
def test_the_scheme_check_stands_on_its_own(url):
    with pytest.raises(UnsafeURLError, match="http"):
        assert_safe_url(url)


@pytest.mark.parametrize("url", BLOCKED_SCHEMES, ids=[u[:28] for u in BLOCKED_SCHEMES])
def test_non_http_schemes_are_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", ["", "   ", "not a url", "http://", "https:///path"])
def test_malformed_input_is_refused(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize(
    "host",
    [
        "internal.example.com",
        "loopback.example.com",
        "metadata.example.com",
        "v6loop.example.com",
    ],
)
def test_a_public_looking_name_that_resolves_to_a_private_address_is_refused(host):
    """The name looks harmless; only resolving it shows where it points."""
    with pytest.raises(UnsafeURLError):
        assert_safe_url(f"https://{host}/page")


def test_a_name_with_both_public_and_private_addresses_is_refused():
    """Checking only the first address would let this through half the time."""
    with pytest.raises(UnsafeURLError):
        assert_safe_url("https://rebind.example.com/page")


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
    async def test_redirect_to_a_name_that_resolves_privately_is_refused(self):
        """A redirect to a hostname, not a literal IP, still has to be resolved."""
        respx.get("https://evil.example.com/start").mock(
            return_value=httpx.Response(302, headers={"location": "https://internal.example.com/admin"})
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://evil.example.com/start")

    @respx.mock
    async def test_the_start_url_resolves_so_the_redirect_check_is_what_refuses(self):
        """Proves the premise of the redirect tests: the starting host is fine,
        so any refusal comes from the redirect hop and nothing else."""
        assert assert_safe_url("https://evil.example.com/start")

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
        """The error alone cannot show the limit works, since an unbounded loop
        ends in the same error, just later. Counting the requests actually made
        is what proves it stops."""
        from app.utils.safe_fetch import MAX_REDIRECTS

        route = respx.get("https://loop.example.com/a").mock(
            return_value=httpx.Response(302, headers={"location": "https://loop.example.com/a"})
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError, match="redirect"):
                await safe_get(client, "https://loop.example.com/a")
        assert route.call_count == MAX_REDIRECTS + 1

    @respx.mock
    async def test_oversized_response_is_refused(self):
        respx.get("https://big.example.com/page").mock(
            return_value=httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError):
                await safe_get(client, "https://big.example.com/page")

    @respx.mock
    async def test_a_server_that_lies_about_content_length_is_still_capped(self):
        """The declared length is only a claim. Here the header says 10 bytes and
        the body is far over the limit, so only counting what actually arrives
        can stop it."""
        respx.get("https://liar.example.com/page").mock(
            return_value=httpx.Response(
                200,
                content=b"x" * (MAX_RESPONSE_BYTES + 5),
                headers={"content-length": "10"},
            )
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError, match="too large"):
                await safe_get(client, "https://liar.example.com/page")

    @respx.mock
    async def test_the_body_is_abandoned_at_the_limit_not_read_in_full(self):
        """Memory is only bounded if reading STOPS at the limit. An endless body
        must not be consumed to the end."""
        consumed = 0

        async def endless():
            nonlocal consumed
            while True:
                consumed += 1024 * 1024
                yield b"x" * (1024 * 1024)

        respx.get("https://endless.example.com/page").mock(
            return_value=httpx.Response(200, content=endless())
        )
        async with httpx.AsyncClient() as client:
            with pytest.raises(UnsafeURLError, match="too large"):
                await safe_get(client, "https://endless.example.com/page")
        # The limit is 2 MB. Reading a few chunks past it is fine; reading on
        # forever is not.
        assert consumed <= MAX_RESPONSE_BYTES + 4 * 1024 * 1024

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
