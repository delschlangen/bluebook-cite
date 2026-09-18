"""Guarded outbound fetching for user-supplied URLs.

The citation tools accept a URL from the visitor and fetch it to scrape
metadata. Without a guard that is a server-side request forgery primitive: a
visitor can make the backend issue requests to addresses only the backend can
reach, including the container's own network and cloud metadata endpoints.

The checks here are applied to every hop, because a permitted public host can
redirect to a private one.
"""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

ALLOWED_SCHEMES = {"http", "https"}

# Cloud instance metadata. Reachable from inside most hosted containers and a
# common source of credentials.
BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
}

# Fetching is for HTML metadata. A response larger than this is not a web page
# worth scraping, and streaming it would let a hostile host exhaust memory.
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

MAX_REDIRECTS = 3
FETCH_TIMEOUT = 8.0


class UnsafeURLError(ValueError):
    """Raised when a URL must not be fetched by the server."""


def _address_is_forbidden(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local       # includes 169.254.169.254
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (getattr(ip, "is_site_local", False))
    )


def assert_safe_url(url: str) -> str:
    """Validate a URL for server-side fetching.

    Returns the URL when it is safe. Raises UnsafeURLError otherwise. Every
    hostname is resolved and *all* of its addresses are checked, so a name that
    resolves to both a public and a private address is rejected.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURLError("No URL provided.")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Only http and https URLs can be fetched, not {parsed.scheme!r}."
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise UnsafeURLError("URL has no host.")

    if hostname in BLOCKED_HOSTS or hostname.endswith(".internal"):
        raise UnsafeURLError("That host is not reachable from this service.")

    # A literal IP needs no DNS, but still needs checking.
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        if _address_is_forbidden(literal):
            raise UnsafeURLError("That address is not reachable from this service.")
        return url

    try:
        resolved = socket.getaddrinfo(hostname, parsed.port or 0, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise UnsafeURLError(f"Could not resolve {hostname!r}.") from exc

    if not resolved:
        raise UnsafeURLError(f"Could not resolve {hostname!r}.")

    for info in resolved:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _address_is_forbidden(ip):
            raise UnsafeURLError("That address is not reachable from this service.")

    return url


async def safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET a user-supplied URL with redirects validated hop by hop.

    httpx's follow_redirects would chase a redirect into a private address
    without re-checking it, so redirects are followed manually here.
    """
    current = assert_safe_url(url)

    for _ in range(MAX_REDIRECTS + 1):
        response = await client.get(
            current,
            follow_redirects=False,
            timeout=FETCH_TIMEOUT,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )

        if response.is_redirect:
            location = response.headers.get("location")
            if not location:
                return response
            current = assert_safe_url(str(response.url.join(location)))
            continue

        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise UnsafeURLError("That page is too large to inspect.")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise UnsafeURLError("That page is too large to inspect.")
        return response

    raise UnsafeURLError("Too many redirects.")
