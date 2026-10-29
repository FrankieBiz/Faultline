#!/usr/bin/env python3
"""Point the public judge page at a deployed FaultLine live repair service.

Run from the repository root on your own machine, after deploying the service
(deploy/README.md):

    uv run --no-project python scripts/configure-live-demo.py https://203-0-113-10.sslip.io
    uv run --no-project python scripts/configure-live-demo.py --clear

The tool fetches ``<url>/api/live/status`` as the judge page would (from the
GitHub Pages origin), reports availability, provider, and classification, checks
that the service allows that origin and that the page's Content-Security-Policy
allows connecting to it, and only then rewrites the ``content`` of
``<meta name="faultline-live-api" content="...">`` in docs/index.html. Nothing
else in the page changes. It never commits or publishes: pushing docs/ to main
publishes the page.

Options: ``--dry-run`` shows the change without writing it; ``--clear`` empties
the value (the page then offers only the recorded playback); ``--allow-local``
permits http://127.0.0.1, http://localhost, or http://[::1] for local testing;
``--force`` writes despite a failed check. Exit status is 0 on success, 1 when a
check fails or the page cannot be edited, and 2 for invalid arguments.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PAGE = ROOT / "docs" / "index.html"
PAGE_ORIGIN = "https://frankiebiz.github.io"
META_NAME = "faultline-live-api"
STATUS_PATH = "/api/live/status"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_STATUS_BYTES = 256 * 1024
DEFAULT_PORTS = {"http": 80, "https": 443}
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOSTNAME = re.compile(rf"{LABEL}(?:\.{LABEL})*")
SCHEME_SOURCE = re.compile(r"[a-z][a-z0-9+.-]*:")
HOST_SOURCE = re.compile(r"(?:([a-z][a-z0-9+.-]*)://)?(\*\.)?([^:/]+)(?::(\d+|\*))?(/.*)?")
META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
NAME_ATTR = re.compile(r"""\bname\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
CONTENT_ATTR = re.compile(r"""(\bcontent\s*=\s*)(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
CSP_META = re.compile(
    r"""<meta\b[^>]*\bhttp-equiv\s*=\s*["']content-security-policy["'][^>]*>""", re.IGNORECASE
)


class ConfigureError(Exception):
    """A check failed or the page cannot be edited; the message says why."""


@dataclass(frozen=True)
class Probe:
    """What the deployed service reported to a request from the judge page's origin."""

    status: dict[str, object]
    allow_origin: str | None


def normalize_base_url(raw: str, *, allow_local: bool) -> str:
    """Return ``scheme://host[:port]`` or raise; the page appends the API paths itself."""
    try:
        parts = urlsplit(raw.strip())
        port = parts.port
    except ValueError as exc:
        raise ConfigureError(f"Not a valid URL: {raw!r} ({exc})") from None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in DEFAULT_PORTS or not host:
        raise ConfigureError(f"Expected https://<host>, got {raw!r}")
    if parts.username is not None or parts.password is not None:
        raise ConfigureError("The URL must not contain credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ConfigureError("Give only the origin, such as https://203-0-113-10.sslip.io")
    local = host in LOCAL_HOSTS
    if local and not allow_local:
        raise ConfigureError(f"{host} is local; pass --allow-local to use it for testing")
    if scheme == "http" and not local:
        raise ConfigureError("A public service must use https://")
    if not local and not HOSTNAME.fullmatch(host):
        raise ConfigureError(f"Unsupported host name: {host!r}")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    return f"{scheme}://{netloc}"


def probe_status(base: str, timeout: float) -> Probe:
    """GET the status endpoint with the judge page's Origin, as a browser would."""
    request = Request(
        base + STATUS_PATH,
        headers={"Origin": PAGE_ORIGIN, "Accept": "application/json"},
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_STATUS_BYTES + 1)
            allow_origin = response.headers.get("Access-Control-Allow-Origin")
    except HTTPError as exc:
        exc.close()
        raise ConfigureError(f"{base}{STATUS_PATH} answered HTTP {exc.code}") from None
    except (OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        raise ConfigureError(f"Could not reach {base}{STATUS_PATH}: {reason}") from None
    if len(body) > MAX_STATUS_BYTES:
        raise ConfigureError("The status response is unexpectedly large")
    try:
        status = json.loads(body)
    except ValueError:
        raise ConfigureError("The status response is not JSON") from None
    if not isinstance(status, dict) or not isinstance(status.get("available"), bool):
        raise ConfigureError("The status response has no boolean 'available' field")
    return Probe(status=status, allow_origin=allow_origin)


def _source_allows(source: str, scheme: str, host: str, port: int) -> bool:
    """Match one CSP source expression against the status URL (CSP Level 3 subset)."""
    source = source.lower()
    if source == "*":
        return scheme in DEFAULT_PORTS
    if source == "'self'":
        return f"{scheme}://{host}" == PAGE_ORIGIN and port == DEFAULT_PORTS[scheme]
    if source.startswith("'"):
        return False
    if SCHEME_SOURCE.fullmatch(source):
        return source[:-1] in (scheme, "http" if scheme == "https" else scheme)
    match = HOST_SOURCE.fullmatch(source)
    if match is None:
        return False
    source_scheme, wildcard, source_host, source_port, source_path = match.groups()
    # A scheme-less source takes the page's https scheme; http: also admits https.
    if (source_scheme or "https") not in (scheme, "http" if scheme == "https" else scheme):
        return False
    if wildcard and not host.endswith("." + source_host):
        return False
    if not wildcard and host != source_host.strip("[]"):
        return False
    if source_port != "*" and port != (int(source_port) if source_port else DEFAULT_PORTS[scheme]):
        return False
    if source_path and source_path != "/":
        return STATUS_PATH.startswith(source_path) if source_path.endswith("/") else False
    return True


def csp_allows(page: str, base: str) -> bool:
    """Whether the page's meta Content-Security-Policy lets scripts fetch ``base``."""
    tag = CSP_META.search(page)
    if tag is None:
        return True
    content = CONTENT_ATTR.search(tag.group(0))
    if content is None:
        return True
    policy = html.unescape(content.group(2) if content.group(2) is not None else content.group(3))
    directives: dict[str, list[str]] = {}
    for directive in policy.split(";"):
        tokens = directive.split()
        if tokens:
            directives.setdefault(tokens[0].lower(), tokens[1:])
    sources = directives.get("connect-src", directives.get("default-src"))
    if sources is None:
        return True
    parts = urlsplit(base)
    scheme, host = parts.scheme, parts.hostname or ""
    port = parts.port or DEFAULT_PORTS[scheme]
    return any(_source_allows(source, scheme, host, port) for source in sources)


def _live_api_tag(page: str) -> re.Match[str]:
    found = []
    for tag in META_TAG.finditer(page):
        name = NAME_ATTR.search(tag.group(0))
        if name is not None and (name.group(1) or name.group(2) or "").lower() == META_NAME:
            found.append(tag)
    if not found:
        raise ConfigureError(
            f'The page has no <meta name="{META_NAME}" content=""> tag yet; '
            "add it to the page <head> first"
        )
    if len(found) > 1:
        raise ConfigureError(f'Found {len(found)} <meta name="{META_NAME}"> tags; expected one')
    return found[0]


def current_live_api(page: str) -> str:
    """Return the configured API base URL, or an empty string."""
    content = CONTENT_ATTR.search(_live_api_tag(page).group(0))
    if content is None:
        return ""
    return html.unescape(content.group(2) if content.group(2) is not None else content.group(3))


def set_live_api(page: str, value: str) -> str:
    """Replace only the meta tag's content value; every other byte stays the same."""
    tag = _live_api_tag(page)
    content = CONTENT_ATTR.search(tag.group(0))
    if content is None:
        raise ConfigureError(f'The <meta name="{META_NAME}"> tag has no content attribute')
    group = 2 if content.group(2) is not None else 3
    start = tag.start() + content.start(group)
    end = tag.start() + content.end(group)
    return page[:start] + html.escape(value, quote=True) + page[end:]


def _write_atomically(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _shown(value: object) -> str:
    """Render a service-supplied value for the terminal without control characters."""
    return "".join(character for character in str(value) if character.isprintable())[:200]


def _report(probe: Probe) -> list[str]:
    """Print what the service reported; return problems that should block the edit."""
    status = probe.status
    print(f"  available:      {_shown(status.get('available'))}")
    if status.get("reason"):
        print(f"  reason:         {_shown(status.get('reason'))}")
    print(f"  provider:       {_shown(status.get('provider'))} / {_shown(status.get('model'))}")
    print(f"  classification: {_shown(status.get('classification'))}")
    limits = status.get("limits")
    if isinstance(limits, dict):
        print(
            f"  limits:         {_shown(limits.get('daily_remaining'))} of "
            f"{_shown(limits.get('daily_cap'))} runs left today, "
            f"{_shown(limits.get('per_client_per_hour'))} per visitor per hour"
        )
    if status.get("available") is not True:
        print("  note:           not available now; the page will offer the recorded playback")
    problems = []
    if probe.allow_origin not in (PAGE_ORIGIN, "*"):
        problems.append(
            f"The service does not allow {PAGE_ORIGIN} (Access-Control-Allow-Origin: "
            f"{probe.allow_origin or 'absent'}); check LIVE_DEMO_ALLOWED_ORIGINS"
        )
    if status.get("classification") != "meta_model":
        print(
            "  note:           not classified meta_model; the page will not describe "
            "these runs as Meta"
        )
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Set or clear the live service URL in the judge page."
    )
    parser.add_argument("url", nargs="?", help="Service origin, e.g. https://1-2-3-4.sslip.io")
    parser.add_argument("--clear", action="store_true", help="Empty the configured URL")
    parser.add_argument("--allow-local", action="store_true", help="Allow loopback http URLs")
    parser.add_argument("--dry-run", action="store_true", help="Show the change only")
    parser.add_argument("--force", action="store_true", help="Write despite failed checks")
    parser.add_argument("--timeout", type=float, default=8.0, help="Status request seconds")
    parser.add_argument("--page", type=Path, default=DEFAULT_PAGE, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.clear == (arguments.url is not None):
        parser.error("give either a service URL or --clear")

    try:
        page = arguments.page.read_bytes().decode("utf-8")
        old = current_live_api(page)
        problems: list[str] = []
        if arguments.clear:
            new = ""
        else:
            new = normalize_base_url(arguments.url, allow_local=arguments.allow_local)
            print(f"Checking {new}{STATUS_PATH} as {PAGE_ORIGIN} would")
            try:
                problems.extend(_report(probe_status(new, arguments.timeout)))
            except ConfigureError as exc:
                problems.append(str(exc))
            if not csp_allows(page, new):
                problems.append(
                    "The page's Content-Security-Policy does not allow connecting to "
                    f"{new}; add it (or https:) to connect-src in docs/index.html"
                )
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        if problems and not arguments.force:
            print("docs/index.html not changed (use --force to write anyway).", file=sys.stderr)
            return 1
        updated = set_live_api(page, new)
    except (ConfigureError, OSError, UnicodeDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if updated == page:
        print(f"Already set: content={old!r}. Nothing to change.")
        return 0
    if arguments.dry_run:
        diff = difflib.unified_diff(
            page.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{arguments.page.name}",
            tofile=f"b/{arguments.page.name}",
            n=0,
        )
        sys.stdout.writelines(diff)
        print("Dry run: nothing written.")
        return 0
    try:
        _write_atomically(arguments.page, updated)
    except OSError as exc:
        print(f"error: could not write {arguments.page}: {exc}", file=sys.stderr)
        return 1
    print(f"Updated {arguments.page}: content {old!r} -> {new!r}")
    print("Review with `git diff docs/index.html`; pushing it to main publishes the page.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
