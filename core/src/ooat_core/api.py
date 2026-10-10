"""The HTTP shell of `ooat serve` (design 05 §5, §6, §7; ADR 0016): settings, who is asking, and the guards.

One process: this API, the sign-in page and the runner. Every endpoint is authenticated except the sign-in page and
`POST /api/v1/login`. A web session (cookie + CSRF token) acts as the operator who signed in; a bearer token acts as
the operator who issued it, within its scopes and its data-class cap. Every request's Host must be one this server
answers to (DNS rebinding), an unsafe request from a browser must carry this server's Origin, and the log records
method, path and status only. The resources are in endpoints.py.
"""

import hmac
import ipaddress
import logging
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import hil, tokens, views
from .artifacts import ArtifactStore
from .backends import LedgerBusyError
from .blobs import BlobStore
from .config import Config
from .connectors.registry import Registry
from .credentials_env import SecretResolver
from .gate import settings_from_config
from .gateway import Gateway
from .ledger import Ledger
from .rating import AlreadyRated, NotClosed
from .routing import RoutingPolicy
from .runner import Runner
from .runtime import Runtime, TaskClosed, UnknownTask
from .sessions import SESSION_TTL, Sessions, login_folder, redeem_login_code
from .validation import SpecValidationError

log = logging.getLogger("ooat.serve")
MAX_BODY = 20 * 1024 * 1024  # design 05 §5: 413 TOO_LARGE above it
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})
SESSION_COOKIE = "ooat_session"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
}


@dataclass(frozen=True)
class ServeSettings:
    ledger_url: str
    blobs_dir: Path
    operator: str | None = None  # [serve] operator: who the start-up sign-in link is for
    host: str = "127.0.0.1"
    port: int = 8765
    hosts: tuple[str, ...] = ()  # further names the Host header may carry, e.g. the machine's DNS name
    tls: bool = False

    @property
    def loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.host).is_loopback
        except ValueError:
            return self.host == "localhost"

    @property
    def session_cap(self) -> str | None:
        """A web session is uncapped on loopback; served beyond it, it is capped like a token (design 05 §14)."""
        return None if self.loopback else "internal"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return LOOPBACK_NAMES | {h.lower() for h in self.hosts} | ({self.host.lower()} if not self.loopback else set())


@dataclass(frozen=True)
class Principal:
    operator: str
    channel: str  # "web" or "token:<id>"
    scopes: frozenset[str]
    max_data_class: str | None  # None: no cap


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def error_response(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details}}, status_code=status)


class Server:
    """What the handlers share. Each thread gets its own ledger connection and Runtime (SQLite stays per thread)."""

    def __init__(self, settings: ServeSettings, config: Config, registry: Registry, routing: RoutingPolicy,
                 clock: Callable[[], datetime]):
        self.settings, self.config, self.registry, self.routing, self.clock = settings, config, registry, routing, clock
        self.sessions = Sessions()
        self.runner = Runner(self.new_runtime, clock=clock)
        self._local = threading.local()

    def new_runtime(self) -> Runtime:
        ledger = Ledger.open(self.settings.ledger_url)
        gateway = Gateway(ledger, self.registry, self.routing, self.config, SecretResolver(self.config),
                          clock=self.clock)
        return Runtime(ledger, gateway, ArtifactStore(ledger, BlobStore(self.settings.blobs_dir)),
                       settings_from_config(self.config), clock=self.clock)

    def runtime(self) -> Runtime:
        """This thread's Runtime (API handlers run in a thread pool)."""
        runtime = getattr(self._local, "runtime", None)
        if runtime is None:
            runtime = self._local.runtime = self.new_runtime()
        return runtime


def server_of(request: Request) -> Server:
    return request.app.state.server


# Who is asking ----------------------------------------------------------------------------------------------------

def principal(request: Request) -> Principal:
    server = server_of(request)
    now = server.clock()
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, presented = header.partition(" ")
        token = tokens.authenticate(server.runtime().ledger.events(types=tokens.EVENTS), presented.strip(), now) \
            if scheme.lower() == "bearer" else None
        if token is None:
            raise ApiError(401, "UNAUTHENTICATED", "unknown, expired or revoked token")
        return Principal(token.operator, f"token:{token.id}", token.scopes, token.max_data_class)
    cookie = request.cookies.get(SESSION_COOKIE)
    session = server.sessions.get(cookie, now) if cookie else None
    if session is None:
        raise ApiError(401, "UNAUTHENTICATED", "sign in with the link `ooat login --operator <name>` prints")
    if request.method not in SAFE_METHODS and not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode("utf-8"), session.csrf.encode("utf-8")):
        raise ApiError(403, "CSRF", "missing or wrong X-CSRF-Token header")
    return Principal(session.operator, "web", frozenset(tokens.SCOPES), server.settings.session_cap)


def scope(name: str) -> Callable[..., Principal]:
    def check(who: Principal = Depends(principal)) -> Principal:
        if name not in who.scopes:
            raise ApiError(403, "SCOPE", f"this token has no {name} scope")
        return who
    return check


def require_within(who: Principal, data_class: str) -> None:
    """A write on content above the reader's cap is refused like a read is stubbed (design 05 §14)."""
    if not views.within(data_class, who.max_data_class):
        raise ApiError(403, "DATA_CLASS_ABOVE_TOKEN", f"this is {data_class} data, above {who.max_data_class}")


# The app ----------------------------------------------------------------------------------------------------------

def create_app(settings: ServeSettings, *, config: Config, registry: Registry, routing: RoutingPolicy,
               clock: Callable[[], datetime], start_runner: bool = True) -> FastAPI:
    server = Server(settings, config, registry, routing, clock)

    @asynccontextmanager
    async def lifespan(app):
        if start_runner:
            server.runner.start()
        yield
        if start_runner:
            server.runner.stop()

    app = FastAPI(title="OOAT", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.server = server
    _guards(app, settings)
    _errors(app)
    app.include_router(login_routes())
    app.include_router(session_routes(), prefix="/api/v1")

    return app


def _origin_allowed(origin: str, settings: ServeSettings) -> bool:
    parts = urlsplit(origin)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return False
    return parts.scheme == ("https" if settings.tls else "http") and (parts.hostname or "") in settings.allowed_hosts \
        and port == settings.port


def _unsafe_allowed(request: Request, settings: ServeSettings) -> bool:
    """A browser sends Origin on every unsafe request; it must be this server. A bearer client (a bot) need not."""
    origin = request.headers.get("origin")
    if origin is not None:
        return _origin_allowed(origin, settings)
    return request.headers.get("authorization") is not None


def _guards(app: FastAPI, settings: ServeSettings) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = urlsplit("//" + request.headers.get("host", "")).hostname or ""
        length = request.headers.get("content-length")
        if host.lower() not in settings.allowed_hosts:  # stops DNS-rebinding pages from reaching the local API
            response = error_response(400, "HOST_NOT_ALLOWED", "this Host is not served")
        elif request.method not in SAFE_METHODS and not _unsafe_allowed(request, settings):
            response = error_response(403, "ORIGIN_NOT_ALLOWED", "an unsafe request needs this server's Origin")
        elif request.method not in SAFE_METHODS and length is None:
            response = error_response(411, "LENGTH_REQUIRED", "send a Content-Length")
        elif length is not None and not (length.isascii() and length.isdigit()):
            response = error_response(400, "INVALID", "Content-Length must be a number")
        elif int(length or 0) > MAX_BODY:
            response = error_response(413, "TOO_LARGE", "a request may carry at most 20 MB")
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        log.info("%s %s %s", request.method, request.url.path, response.status_code)  # no query, headers or body
        return response


def _errors(app: FastAPI) -> None:
    def handler(status: int, code: str):
        async def handle(request, error):
            return error_response(status, code, str(error))
        return handle

    @app.exception_handler(ApiError)
    async def api_error(request, error: ApiError):
        return error_response(error.status, error.code, error.message, error.details)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error: RequestValidationError):
        # Pydantic's details echo the input; keep only where and what, never an attachment's content.
        details = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]
        return error_response(400, "INVALID", "the request does not match the API", details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error: StarletteHTTPException):
        return error_response(error.status_code, "NOT_FOUND" if error.status_code == 404 else "INVALID",
                              str(error.detail))

    # The functions the CLI calls raise these; the API maps them, it adds no rules of its own.
    for kind, status, code in ((SpecValidationError, 422, "SPEC_VALIDATION"), (LedgerBusyError, 503, "LEDGER_BUSY"),
                               (UnknownTask, 404, "NOT_FOUND"), (hil.UnknownRequest, 404, "NOT_FOUND"),
                               (hil.AlreadyAnswered, 409, "ALREADY_ANSWERED"), (NotClosed, 409, "NOT_CLOSED"),
                               (AlreadyRated, 409, "ALREADY_RATED"), (TaskClosed, 409, "NOT_OPEN"),
                               (hil.R3NeedsBoundIdentity, 403, "R3_NEEDS_BOUND_IDENTITY"),
                               (ValueError, 400, "INVALID")):
        app.add_exception_handler(kind, handler(status, code))


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=128)


def login_routes() -> APIRouter:
    """The sign-in page and the code exchange: the only routes without authentication."""
    router = APIRouter()
    web = files("ooat_core") / "web"

    @router.get("/login")
    def login_page() -> Response:
        return Response((web / "login.html").read_bytes(), media_type="text/html; charset=utf-8")

    @router.get("/login.js")
    def login_script() -> Response:
        return Response((web / "login.js").read_bytes(), media_type="text/javascript; charset=utf-8")

    @router.post("/api/v1/login")
    def login(body: LoginIn, request: Request) -> JSONResponse:
        server = server_of(request)
        folder = login_folder(server.settings.ledger_url)
        operator = redeem_login_code(folder, body.code, server.clock()) if folder else None
        if operator is None:
            raise ApiError(401, "UNAUTHENTICATED", "this sign-in link is unknown, used or expired; run `ooat login`")
        cookie, session = server.sessions.open(operator, server.clock())
        response = JSONResponse({"operator": operator, "csrf": session.csrf})
        response.set_cookie(SESSION_COOKIE, cookie, max_age=int(SESSION_TTL.total_seconds()), httponly=True,
                            samesite="strict", secure=server.settings.tls, path="/")
        return response

    return router


def session_routes() -> APIRouter:
    router = APIRouter()

    @router.post("/logout")
    def logout(request: Request, who: Principal = Depends(principal)) -> JSONResponse:
        server_of(request).sessions.close(request.cookies.get(SESSION_COOKIE, ""))
        response = JSONResponse({"operator": who.operator})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @router.get("/me")
    def me(request: Request, who: Principal = Depends(principal)) -> dict:
        found = {"operator": who.operator, "channel": who.channel, "scopes": sorted(who.scopes),
                 "max_data_class": who.max_data_class}
        if who.channel == "web":  # the page needs it after a reload; no other origin can read this response
            server = server_of(request)
            found["csrf"] = server.sessions.get(request.cookies[SESSION_COOKIE], server.clock()).csrf
        return found

    @router.get("/status")
    def status(request: Request, who: Principal = Depends(scope("read"))) -> dict:
        return {"runner": server_of(request).runner.status()}

    return router
