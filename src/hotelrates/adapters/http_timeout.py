"""Bounded timeouts and retries for outbound HTTP (Google Sheets).

gspread passes ``timeout=None`` through to requests, and requests treats that
as "wait forever". A stalled TLS connection then blocks the scheduler the same
way an XML-RPC call without a socket timeout does.
"""
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class TimeoutHTTPAdapter(HTTPAdapter):
    """Use a default timeout when the caller does not set one."""

    def __init__(self, timeout, *args, **kwargs):
        self.timeout = timeout
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.timeout
        return super().send(request, **kwargs)


class LoggingRetry(Retry):
    """Retry transient HTTP failures and log each retry before sleeping."""

    def increment(self, method=None, url=None, response=None, error=None, _pool=None, _stacktrace=None):
        retry = super().increment(
            method=method,
            url=url,
            response=response,
            error=error,
            _pool=_pool,
            _stacktrace=_stacktrace,
        )
        status = getattr(response, "status", None) if response is not None else None
        retriable_status = bool(self.status_forcelist) and status in self.status_forcelist
        if error is not None or retriable_status:
            detail = repr(error) if error is not None else f"HTTP {status}"
            logger.warning(f"HTTP {method} {url} failed ({detail}); retrying")
        return retry


def mount_http_timeouts(session, timeout, retries, backoff_factor=0.5, backoff_max=8):
    """Mount a timeout + retry adapter for http and https on ``session``."""
    retry = LoggingRetry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        redirect=3,
        backoff_factor=backoff_factor,
        backoff_max=backoff_max,
        status_forcelist=(408, 429, 500, 502, 503, 504),
        allowed_methods=frozenset(
            ["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
        ),
        respect_retry_after_header=False,
        raise_on_status=False,
    )
    adapter = TimeoutHTTPAdapter(timeout=timeout, max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
