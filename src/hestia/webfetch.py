"""Sandboxed web fetch: the only outbound HTTP the agent gets.

SSRF guard: http/https only, hostname resolved and rejected when any address
is private, loopback, link-local, reserved, multicast, or unspecified;
redirects are validated one hop at a time. Note: this does not defend against
DNS rebinding, which needs a custom resolver; acceptable for a self-hosted,
single-owner app.

No JavaScript rendering: static HTML is converted to text with the stdlib.
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_BYTES = 500_000
MAX_REDIRECTS = 3
TIMEOUT = 15.0


class FetchError(ValueError):
    """Raised for blocked or failed fetches; mapped to tool errors."""


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _validate(url: str, allow_local: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError("only http and https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise FetchError(f"could not resolve host: {host}") from e
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if allow_local and (
            address.is_loopback or (address.is_private and not address.is_link_local)
        ):
            # explicit per-project opt-in for local dev servers; link-local
            # (cloud metadata) stays blocked even then
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise FetchError(f"blocked address for host: {host}")
    return url


def _decode(response: httpx.Response) -> tuple[str, str]:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    body = response.content[:MAX_BYTES]
    text = body.decode(response.encoding or "utf-8", "replace")
    if content_type in ("text/html", "application/xhtml+xml"):
        parser = _TextExtractor()
        parser.feed(text)
        return "text/html", parser.text()
    return content_type or "text/plain", text


def fetch(url: str) -> dict:
    """Fetch a URL with SSRF protection. Returns {url, content_type, text, bytes}."""
    current = _validate((url or "").strip())
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                response = client.get(current, headers={"User-Agent": "hestia-agent/1.0"})
            except httpx.HTTPError as e:
                raise FetchError(f"fetch failed: {str(e)[:200]}") from e
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise FetchError("redirect without location")
                current = _validate(urljoin(current, location))
                continue
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            content_type, text = _decode(response)
            return {
                "url": current,
                "content_type": content_type,
                "text": text,
                "bytes": len(response.content),
            }
    raise FetchError("too many redirects")
