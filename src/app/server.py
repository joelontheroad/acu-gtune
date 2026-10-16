# SPDX-FileCopyrightText: 2026 Joel Greenberg
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Lightweight local web server adhering to localhost binding, W3C CSP, and launch token auth.

Provides an isolated, localhost-only FastAPI application serving the stroboscopic
tuner web interface, handling session-authenticated preset persistence, and enforcing
defense-in-depth HTTP security headers (CWE-208, CWE-352, CWE-693).
"""

import secrets
import sys
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse

from app.config import TunerPreset, load_preset, save_preset
from app.dsp import TUNING_PRESETS


def create_app(auth_token: Optional[str] = None) -> FastAPI:
    """Create an authenticated, hardened local FastAPI application.

    Configures security middleware, binds an ephemeral session token, and registers
    REST API routes for tuner configuration and preset management.

    Args:
        auth_token: Optional predetermined authentication token. Generates a cryptographically
            secure 32-byte hex token if omitted.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="acu-gtune Local Server",
        description="Localhost-bound web server for acu-gtune",
        docs_url=None,  # Disable public swagger docs by default for privacy
        redoc_url=None,
    )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """Enforce W3C Content Security Policy and modern browser defense headers.

        Args:
            request: Incoming HTTP request.
            call_next: Request handler pipeline callable.

        Returns:
            Response with hardened HTTP security headers attached.
        """
        response = await call_next(request)
        # SECURITY: Defense-in-depth headers. Enforce restrictive Content-Security-Policy (CSP)
        # restricting origins to 'self', block iframe framing to eliminate clickjacking (CWE-1021),
        # prevent MIME sniffing (CWE-79), and drop referrer metadata.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "object-src 'none'; frame-ancestors 'none';"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # SECURITY: Generate cryptographically random 32-byte hex launch token (CWE-330).
    server_token = auth_token or secrets.token_hex(32)
    app.state.auth_token = server_token

    def verify_auth(
        request: Request,
        token_query: Optional[str] = Query(None, alias="token"),
        authorization: Optional[str] = Header(None),
    ):
        """Verify the ephemeral launch token via query parameter, header, or cookie.

        Args:
            request: Incoming HTTP request.
            token_query: Launch token passed as a URL query parameter.
            authorization: HTTP Authorization header containing a Bearer token.

        Returns:
            The validated candidate token string.

        Raises:
            HTTPException: If no valid token is provided or the token fails comparison (401).
        """
        cookie_token = request.cookies.get("acu-gtune_session")
        bearer_token = None
        if authorization and authorization.startswith("Bearer "):
            bearer_token = authorization.split(" ")[1]

        candidate = token_query or bearer_token or cookie_token
        # SECURITY: Constant-time comparison prevents timing attacks (CWE-208)
        # when authenticating requests against the ephemeral launch token.
        if not candidate or not secrets.compare_digest(candidate, app.state.auth_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Valid ephemeral launch token required.",
            )
        return candidate

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, response: Response, token: Optional[str] = Query(None)):
        """Serve the local single-page stroboscopic tuner application.

        Args:
            request: Incoming HTTP request.
            response: Outgoing HTTP response for cookie assignment.
            token: Optional ephemeral token from URL query string.

        Returns:
            Rendered HTML content for the stroboscopic web tuner.
        """
        # SECURITY: Validate launch token via constant-time digest comparison (CWE-208).
        if token and secrets.compare_digest(token, app.state.auth_token):
            # SECURITY: Set SameSite=Strict and HttpOnly on session cookie to protect
            # against cross-site script access (XSS) and cross-site request forgery (CSRF).
            response.set_cookie(
                key="acu-gtune_session",
                value=token,
                httponly=True,
                samesite="strict",
                secure=False,  # Allow http on localhost loopback
            )
        else:
            cookie_token = request.cookies.get("acu-gtune_session")
            # SECURITY: Timing-safe validation for existing session cookie.
            if not cookie_token or not secrets.compare_digest(cookie_token, app.state.auth_token):
                msg = (
                    "<h3>401 Unauthorized</h3>"
                    "<p>Please open the authenticated link printed in your terminal.</p>"
                )
                return HTMLResponse(msg, status_code=401)

        html_path = Path(__file__).parent / "web" / "index.html"
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    @app.get("/api/preset", response_model=TunerPreset)
    async def get_active_preset(auth: str = Depends(verify_auth)):
        """Retrieve the currently active tuner configuration preset.

        Args:
            auth: Verified launch token string.

        Returns:
            Active TunerPreset instance.
        """
        return load_preset("default")

    @app.post("/api/preset")
    async def update_preset(preset: TunerPreset, auth: str = Depends(verify_auth)):
        """Persist updated tuner preset parameters to disk.

        Args:
            preset: Deserialized and validated TunerPreset payload.
            auth: Verified launch token string.

        Returns:
            Dictionary confirming save status and destination filepath.

        Raises:
            HTTPException: If preset validation or filesystem write fails (400).
        """
        try:
            path = save_preset(preset)
            return {"status": "ok", "path": str(path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/tunings")
    async def get_tuning_definitions(auth: str = Depends(verify_auth)):
        """Retrieve instrument tuning note definitions and presets.

        Args:
            auth: Verified launch token string.

        Returns:
            Dictionary mapping instrument types to tuning note definitions.
        """
        return TUNING_PRESETS

    return app


def run_local_server(port: int = 8080, host: str = "127.0.0.1", open_browser: bool = True) -> None:
    """Run the local uvicorn server strictly bound to localhost with auto-open and terminal links.

    Args:
        port: Port number on which the HTTP server will listen (default 8080).
        host: Host network interface (defaults strictly to '127.0.0.1').
        open_browser: Flag to automatically launch default browser on startup.
    """
    import base64
    import os
    import threading
    import webbrowser

    import uvicorn

    # SECURITY: Generate cryptographically random 32-byte hex launch token (CWE-330).
    token = secrets.token_hex(32)
    app = create_app(auth_token=token)
    url = f"http://{host}:{port}/?token={token}"

    # Auto-open browser via non-blocking background timer
    if open_browser:
        def _open() -> None:
            try:
                # Suppress noisy browser engine console messages (e.g. Chromium zygote pipe notices)
                devnull = os.open(os.devnull, os.O_RDWR)
                old_stdout = os.dup(1)
                old_stderr = os.dup(2)
                try:
                    os.dup2(devnull, 1)
                    os.dup2(devnull, 2)
                    webbrowser.open(url)
                finally:
                    os.dup2(old_stdout, 1)
                    os.dup2(old_stderr, 2)
                    os.close(old_stdout)
                    os.close(old_stderr)
                    os.close(devnull)
            except Exception as exc:
                sys.stderr.write(f"[acu-gtune] Notice: browser auto-open skipped: {exc}\n")

        timer = threading.Timer(0.35, _open)
        timer.daemon = True
        timer.start()

    # Emit clickable OSC 8 hyperlink and OSC 52 clipboard sequence on interactive terminals
    is_tty = sys.stderr.isatty()
    if is_tty:
        clickable_link = f"\033]8;;{url}\033\\{url}\033]8;;\033\\"
        b64_url = base64.b64encode(url.encode("utf-8")).decode("ascii")
        osc52_clip = f"\033]52;c;{b64_url}\a"
        sys.stderr.write(osc52_clip)
    else:
        clickable_link = url

    sys.stderr.write(f"\n[acu-gtune] Local server running at: {clickable_link}\n")
    # SECURITY: Inform user of loopback binding isolation.
    sys.stderr.write(
        "[acu-gtune] Bound strictly to localhost for privacy and security. "
        "Press Ctrl+C to exit.\n\n"
    )
    sys.stderr.flush()

    # SECURITY: Server binds strictly to loopback interface (127.0.0.1) by default
    # to prevent exposing the audio processing engine to external networks.
    uvicorn.run(app, host=host, port=port, log_level="warning")
