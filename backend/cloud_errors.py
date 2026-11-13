"""Classify broken transports and log diagnostics without authentication data."""
import errno
import logging
import re
import ssl

import httpx
import requests
from google.auth.exceptions import TransportError
from urllib3.exceptions import ProtocolError, ProxyError, SSLError, TimeoutError as UrllibTimeout


def exception_chain(error):
    pending, seen = [error], set()
    while pending and len(seen) < 12:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(getattr(current, key, None) for key in
                       ("__cause__", "__context__", "cause", "reason"))


def is_transport_error(error):
    for current in exception_chain(error):
        if isinstance(current, (ConnectionError, TimeoutError, ssl.SSLError,
                httpx.TransportError, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError,
                TransportError, ProtocolError, ProxyError, SSLError, UrllibTimeout)):
            return True
        if isinstance(current, OSError) and current.errno in {
                errno.ECONNRESET, errno.ECONNREFUSED, errno.ECONNABORTED,
                errno.ETIMEDOUT, errno.EPIPE, errno.ENETUNREACH, errno.EHOSTUNREACH,
                10053, 10054, 10060, 10061}:
            return True
        if isinstance(current, RuntimeError) and re.search(
                r"(?:client|session|connection pool).*(?:closed|closing)", str(current), re.I):
            return True
    return False


def redact_cloud_error(value):
    text = str(value)
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
                  "[REDACTED PRIVATE KEY]", text, flags=re.S)
    # Preserve host/path for diagnosis, remove proxy passwords and signed URLs.
    text = re.sub(r"((?:https?|socks5h?|socks4a?)://)[^/\s@]+@", r"\1[REDACTED]@", text, flags=re.I)
    text = re.sub(r"((?:https?|socks5h?|socks4a?)://[^\s?#\x22\x27]+)[?#][^\s\x22\x27]*",
                  r"\1?[REDACTED]", text, flags=re.I)
    text = re.sub(r"\b(?:Bearer|Basic)\s+[^\s\x22\x27,;]+",
                  "[REDACTED AUTHORIZATION]", text, flags=re.I)
    fields = r"private_key|access_token|refresh_token|id_token|token|client_secret|password|authorization|proxy-authorization|cookie|x-goog-api-key|x-api-key|api_key|assertion"
    text = re.sub(r"([\x22\x27]?(?:" + fields + r")[\x22\x27]?\s*[:=]\s*)(?:\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^\s,;}\]]+)",
                  r"\1[REDACTED]", text, flags=re.I)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?",
                  "[REDACTED JWT]", text)
    return text[:1500].replace("\r", " ").replace("\n", " ")


def log_cloud_failure(logger, operation, error):
    # No exc_info: a raw traceback would print unsanitized exception messages.
    detail = " <- ".join(type(exc).__name__ + ": " + redact_cloud_error(exc)
                         for exc in exception_chain(error))
    logger.warning("%s: %s", operation, detail[:3500])


def close_cloud_client(client):
    try:
        close = getattr(client, "close", None)
        if close:
            close()
    except Exception as exc:
        log_cloud_failure(logging.getLogger("vertex_backend.cloud"), "cloud_client_close_failed", exc)
