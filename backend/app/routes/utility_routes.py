
import ipaddress
import socket
import traceback
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_user_from_session
from app.config import APP_ENV

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def validate_external_url(url: str) -> str:
    """Reject unsafe destinations before fetching external resources."""

    url = url.strip()

    try:
        parsed = urlsplit(url)

        if parsed.scheme not in ("http", "https"):
            raise ValueError("Only HTTP and HTTPS URLs are allowed.")

        if not parsed.hostname:
            raise ValueError("Invalid URL: missing hostname.")

        if parsed.username or parsed.password:
            raise ValueError("Credentials in URLs are not allowed.")

        if parsed.port not in (None, 80, 443):
            raise ValueError("Only standard HTTP/HTTPS ports are allowed.")

        hostname = parsed.hostname

        # Resolve the hostname and check every returned address.
        addresses = socket.getaddrinfo(
            hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )

        if not addresses:
            raise ValueError("Could not resolve hostname.")

        for entry in addresses:
            address = ipaddress.ip_address(entry[4][0])

            if not address.is_global:
                raise ValueError(
                    "Private, local, or reserved addresses are blocked."
                )

    except (ValueError, socket.gaierror, OverflowError) as exc:
        raise ValueError(f"Unsafe resource URL: {exc}") from exc

    return url


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status", response_class=HTMLResponse)
def status(request: Request):
    user = get_user_from_session(request)
    return templates.TemplateResponse(
        "status.html",
        {
            "request": request,
            "user": user,
            "env": APP_ENV,
            "python": "3.11",
            "service": "backend",
        },
    )


@router.get("/resources/import", response_class=HTMLResponse)
def import_resource_get(request: Request, url: str = ""):
    user = get_user_from_session(request)

    if not user:
        return RedirectResponse("/login", status_code=302)

    body = ""
    error = ""

    if url:
        try:
            safe_url = validate_external_url(url)

            # Ignore proxy configuration from environment variables.
            with requests.Session() as session:
                session.trust_env = False

                response = session.get(
                    safe_url,
                    timeout=5,
                    allow_redirects=False,
                    stream=True,
                )

                if 300 <= response.status_code < 400:
                    raise ValueError(
                        "Redirects are not allowed for resource imports."
                    )

                response.raise_for_status()

                # Only import text-based responses.
                content_type = response.headers.get(
                    "Content-Type", ""
                ).lower()

                if not (
                    content_type.startswith("text/")
                    or "application/json" in content_type
                ):
                    raise ValueError(
                        "Only text and JSON resources are supported."
                    )

                # Limit how much content is downloaded.
                data = b""
                for chunk in response.iter_content(chunk_size=2048):
                    data += chunk
                    if len(data) >= 4096:
                        break

                body = data[:4096].decode(
                    response.encoding or "utf-8",
                    errors="replace",
                )[:2000]

        except (ValueError, requests.RequestException):
            error = "Resource import failed or URL is not allowed."

    return templates.TemplateResponse(
        "resource_import.html",
        {
            "request": request,
            "user": user,
            "body": body,
            "url": url,
            "error": error,
        },
    )


@router.post("/resources/import", response_class=HTMLResponse)
def import_resource_post(request: Request, url: str = Form(...)):
    return import_resource_get(request, url)


@router.get("/error", response_class=HTMLResponse)
def trigger_error(request: Request):
    try:
        x = 1 / 0
        return {"x": x}
    except Exception:
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "details": traceback.format_exc(),
            },
            status_code=500,
        )
