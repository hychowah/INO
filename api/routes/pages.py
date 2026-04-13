"""SPA page routes served by FastAPI."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter(include_in_schema=False)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
RESERVED_PREFIXES = ("api", "assets", "static")


def _frontend_missing_response() -> HTMLResponse:
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
            <head>
                <meta charset="utf-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <title>Frontend Build Missing</title>
            </head>
            <body>
                <main>
                    <h1>Frontend bundle not built</h1>
                    <p>Build the React frontend before opening browser routes.</p>
                    <p>Run <code>make build-ui</code> from the repository root.</p>
                </main>
            </body>
        </html>
        """.strip()
    )


def _spa_entry_response() -> FileResponse | HTMLResponse:
    spa_entry = FRONTEND_DIST / "index.html"
    if spa_entry.exists():
        return FileResponse(spa_entry)
    return _frontend_missing_response()


def _path_is_reserved(path: str) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in RESERVED_PREFIXES)


def _request_wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return not accept or "text/html" in accept or "*/*" in accept


def _should_serve_spa(request: Request, path: str) -> bool:
    return not _path_is_reserved(path) and _request_wants_html(request)


@router.get("/", response_class=HTMLResponse)
@router.get("/{path:path}", response_class=HTMLResponse)
async def spa_page(request: Request, path: str = ""):
    if not _should_serve_spa(request, path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return _spa_entry_response()
