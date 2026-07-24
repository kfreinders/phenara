from __future__ import annotations

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from gui.routes import analysis, development, schedule_api, scheduler
from phenopi.config import GUI_HOST, GUI_PORT, PROJECT_ROOT


def _secure_response(response, path: str):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(self)"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif response.headers.get("content-type", "").startswith("text/html"):
        response.headers["Cache-Control"] = "no-store"
    return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="Phenopi GUI",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def protect_browser_requests(request, call_next):
        if request.url.path.startswith("/api/"):
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    parsed_length = int(content_length)
                    maximum = (
                        14_000_000
                        if request.url.path
                        in {"/api/analysis/preview", "/api/analysis/roi"}
                        else 1_000_000
                    )
                    too_large = parsed_length < 0 or parsed_length > maximum
                except ValueError:
                    too_large = True
                if too_large:
                    return _secure_response(
                        JSONResponse(
                            {"detail": "Request body is too large."},
                            status_code=413,
                        ),
                        request.url.path,
                    )
            if (
                request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and request.headers.get("x-phenopi-request") != "1"
            ):
                return _secure_response(
                    JSONResponse(
                        {"detail": "Missing Phenopi request marker."},
                        status_code=403,
                    ),
                    request.url.path,
                )

        response = await call_next(request)
        return _secure_response(response, request.url.path)

    app.include_router(schedule_api.router)
    app.include_router(scheduler.router)
    app.include_router(analysis.router)
    app.include_router(development.router)

    react_dir = PROJECT_ROOT / "gui" / "react-dist"
    assets_dir = react_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def react_app(path: str) -> FileResponse:
        index = react_dir / "index.html"
        if not index.exists():
            raise HTTPException(
                status_code=503,
                detail="React GUI has not been built. Run npm run build in gui/frontend.",
            )
        return FileResponse(index)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(
        "gui.app:app",
        host=GUI_HOST,
        port=GUI_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
