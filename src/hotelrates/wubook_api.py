# version 0.9
import errno
import http.client
import os
import socket
import ssl
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from xml.parsers.expat import ExpatError

import xmlrpc.client
from dotenv import load_dotenv
from loguru import logger

C = os.path.abspath(os.path.dirname(__file__))
sys.path.append(C)
load_dotenv()


### ROOM COFIGURATION ###

# différencier chambres "réelles" et chambres "virtuelles"
REAL_ROOMS = {"329039", "329667", "329670", "407751", "469743", "469744"}

type_room = {"329039": "double economic",
             "329667": "double balcony",
             "329670": "triple economic",
             "405126": "single balcony",
             "405127": "single economic",
             "407751": "triple balcony",
             "469743": "familiale",
             "469744": "kichenette"
            }

room_to_code = {"sstd": "405127",
                "sblc": "405126",
                "2C": "329039",
                "dblc": "329667",
                "tstd": "329670",
                "tblc": "407751",
                "fblc": "469743",
                "ktch": "469744"
               }


url = "https://wired.wubook.net/xrws/"


# TODO: faire attention au fichier de logs

# LOAD ID
user = os.getenv('WUBOOK_USER')
pkey = os.getenv('WUBOOK_PKEY')
lcode = os.getenv('WUBOOK_LCODE')
password = os.getenv('WUBOOK_PASSWORD')

MIN_PRICE = 45

# A stalled WuBook TCP connection used to block the scheduler forever
# (no socket timeout on xmlrpc.client.ServerProxy).
RPC_TIMEOUT = float(os.getenv("WUBOOK_RPC_TIMEOUT", "60"))
RPC_ATTEMPTS = int(os.getenv("WUBOOK_RPC_ATTEMPTS", "3"))
RPC_BACKOFF_SECONDS = float(os.getenv("WUBOOK_RPC_BACKOFF", "2"))
RPC_BACKOFF_MAX = float(os.getenv("WUBOOK_RPC_BACKOFF_MAX", "30"))

def _errnos(*names):
    found = set()
    for name in names:
        value = getattr(errno, name, None)
        if isinstance(value, int):
            found.add(value)
    return found


_TRANSIENT_ERRNOS = _errnos(
    "EAI_AGAIN",
    "EAGAIN",
    "ECONNABORTED",
    "ECONNREFUSED",
    "ECONNRESET",
    "EHOSTDOWN",
    "EHOSTUNREACH",
    "ENETDOWN",
    "ENETRESET",
    "ENETUNREACH",
    "EPIPE",
    "ESHUTDOWN",
    "ETIMEDOUT",
    "EWOULDBLOCK",
)
_gai_again = getattr(socket, "EAI_AGAIN", None)
if isinstance(_gai_again, int):
    _TRANSIENT_ERRNOS.add(_gai_again)


def _is_transient(exc):
    """Timeouts, truncated XML (ExpatError), and dropped connections."""
    if isinstance(exc, xmlrpc.client.Fault):
        return False
    if isinstance(exc, xmlrpc.client.ProtocolError):
        code = exc.errcode or 0
        return code in (408, 429) or code >= 500
    if isinstance(exc, socket.gaierror):
        return True
    if isinstance(
        exc,
        (
            TimeoutError,
            ConnectionError,
            http.client.IncompleteRead,
            http.client.BadStatusLine,
            ExpatError,
            xmlrpc.client.ResponseError,
            ssl.SSLError,
        ),
    ):
        return True
    return isinstance(exc, OSError) and getattr(exc, "errno", None) in _TRANSIENT_ERRNOS


class _TimeoutMixin:
    """Set a socket timeout on the connection xmlrpc builds for each host."""

    def __init__(self, *args, timeout=RPC_TIMEOUT, **kwargs):
        self._rpc_timeout = timeout
        super().__init__(*args, **kwargs)

    def make_connection(self, host):
        conn = super().make_connection(host)
        if conn is not None:
            conn.timeout = self._rpc_timeout
        return conn


class TimeoutTransport(_TimeoutMixin, xmlrpc.client.Transport):
    """HTTP transport with a socket timeout."""


class TimeoutSafeTransport(_TimeoutMixin, xmlrpc.client.SafeTransport):
    """HTTPS transport with a socket timeout."""


def _server_proxy(endpoint, timeout=None):
    if timeout is None:
        timeout = RPC_TIMEOUT
    scheme = urllib.parse.urlsplit(endpoint).scheme
    if scheme == "https":
        transport = TimeoutSafeTransport(timeout=timeout)
    elif scheme == "http":
        transport = TimeoutTransport(timeout=timeout)
    else:
        raise ValueError(f"Unsupported WuBook URL scheme: {scheme!r}")
    return xmlrpc.client.ServerProxy(endpoint, transport=transport, verbose=False)


def _close_proxy(server):
    transport = getattr(server, "_ServerProxy__transport", None)
    if transport is None:
        return
    try:
        transport.close()
    except Exception:
        logger.debug("WuBook transport close failed")


def _rpc_call(server, method, *args):
    """Call one XML-RPC method. Retry timeouts and other transient errors."""
    func = getattr(server, method)
    attempts = max(1, int(RPC_ATTEMPTS))
    backoff = float(RPC_BACKOFF_SECONDS)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            return func(*args)
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts or not _is_transient(exc):
                logger.error(
                    f"WuBook {method} failed (attempt {attempt}/{attempts}): {exc!r}"
                )
                raise
            delay = min(backoff * (2 ** (attempt - 1)), float(RPC_BACKOFF_MAX))
            logger.warning(
                f"WuBook {method} transient error (attempt {attempt}/{attempts}): "
                f"{exc!r}; retrying in {delay:.1f}s"
            )
            _close_proxy(server)
            if delay > 0:
                time.sleep(delay)
    raise last_exc


class Wubook:
    def __init__(self):
        self.server = _server_proxy(url)
        self.returnCode, self.token = _rpc_call(
            self.server, "acquire_token", user, password, pkey
        )
        if self.returnCode != 0:
            logger.warning("Can’t connect to server")
        else:
            logger.info("Server connected")

    def __enter__(self):
        return self.server, self.token

    def __exit__(self, exception_type, exception_value, exception_traceback):
        if exception_type is not None:
            logger.error(exception_value)
            logger.error(exception_traceback)
        # Release even after a failed call so a timed-out cycle does not leak
        # the token and block the next acquire_token.
        if self.returnCode != 0:
            return False
        try:
            self.server.release_token(self.token)
        except Exception as exc:
            logger.warning(
                f"Error while releasing token from wubook server: {exc!r}"
            )
        else:
            logger.info("Server disconnected")
        return False


def get_avail(dfrom, dto):
    """Get avail from dfrom to dto in the wubook server
    dfrom and dto: dd/mm/yyyy
    if dfrom < dtoday: dfrom = dtoday
    RETURN {<date>: {
                     <code_chambre>:<disponibilité>, ...}
            ...}"""

    if datetime.strptime(dfrom, "%d/%m/%Y").date() < date.today():
        dfrom = date.today().strftime("%d/%m/%Y")
    with Wubook() as (server, token):
        return_code, avail = _rpc_call(
            server, "fetch_rooms_values", token, lcode, dfrom, dto
        )

    if return_code != 0:
        raise ConnectionError(f"in get_avail({dfrom}, {dto}) error: {avail}")

    dfrom_time = datetime.strptime(dfrom, "%d/%m/%Y")
    dto_time = datetime.strptime(dto, "%d/%m/%Y")
    days_diff = (dto_time - dfrom_time).days

    result = dict()
    for i in range(days_diff):
        temp_dict = dict()
        for room in type_room:
            temp_dict[room] = avail[room][i].get("avail", 0)
        result[(dfrom_time + timedelta(days=i)).strftime("%d/%m/%Y")] = temp_dict
    return result


def get_prices_avail_today():
    """Return prices and avails of today
    If time < 5:00 am: get the price of the previous day"""
    dnow = datetime.now()
    if 0 <= dnow.hour <= 5:
        dnow = datetime.now() - timedelta(days=1)
    dfrom = dto = dnow.strftime("%d/%m/%Y")
    with Wubook() as (server, token):
        return_code, plan_prices = _rpc_call(
            server, "fetch_plan_prices", token, lcode, 0, dfrom, dto
        )
        return_code2, avails = _rpc_call(
            server, "fetch_rooms_values", token, lcode, dfrom, dto
        )
    if return_code != 0:
        raise ConnectionError(f"in get_prices_today(), error: {plan_prices}")
    if return_code2 != 0:
        raise ConnectionError(f"in get_prices_today(), error: {avails}")
    return plan_prices, avails


def upload_prices(dfrom, prices, pid=0):
    """Upload prices

    Args:
        dfrom (str):  Starting Date (european format: 21/12/2021)
        prices (dict): Keys are Room IDs. Values are array of prices. Prices must be greater than 0.01. 
        pid (int, optional): id of the plan prices. Defaults to 0 (Wubook Parity) 
        
        prices = {
            "1": [100, 101, 102],
            "2": [200, 201, 202]
        }
    """
    with Wubook() as (server, token):
        logger.info(
            _rpc_call(server, "update_plan_prices", token, lcode, pid, dfrom, prices)
        )