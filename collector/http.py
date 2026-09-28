"""Shared HTTP session with retries and a polite user agent."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": config.USER_AGENT, "Accept": "*/*"})
        retry = Retry(total=2, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504))
        s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=config.MAX_WORKERS * 2))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


def get(url: str, **kw) -> requests.Response:
    kw.setdefault("timeout", config.HTTP_TIMEOUT)
    r = session().get(url, **kw)
    r.raise_for_status()
    return r
