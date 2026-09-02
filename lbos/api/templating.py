"""Template environment, built once and shared."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from lbos.api.filters import FILTERS

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.filters.update(FILTERS)


def redirect(path: str, message: str | None = None, kind: str = "ok") -> RedirectResponse:
    """Post/Redirect/Get, carrying a one-line message in the query string.

    A refresh after a POST must never re-record an entry, and a message that
    lives in the URL needs no session store on a single-operator machine.
    """
    if message:
        separator = "&" if "?" in path else "?"
        path = f"{path}{separator}{urlencode({'msg': message, 'kind': kind})}"
    return RedirectResponse(path, status_code=303)
