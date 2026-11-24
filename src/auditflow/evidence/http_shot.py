import re
from html import escape
from pathlib import Path

from auditflow.evidence.common import BrowserUnavailable, card, render_png, text_png

_HEADER = re.compile(r"^([\w-]+:)(.*)$")


def _exchange_rows(message: str, patterns: list[str]) -> list[tuple[str, bool]]:
    return [(line, any(pattern in line for pattern in patterns)) for line in message.splitlines()]


def _panel(label: str, rows: list[tuple[str, bool]]) -> str:
    rendered = [f'<section class="panel"><h2>{label}</h2>']
    headers = True
    for line, hit in rows:
        if not line:
            headers = False
        match = _HEADER.match(line) if headers else None
        fragment = escape(line)
        if match:
            fragment = f'<span class="header-name">{escape(match[1])}</span>{escape(match[2])}'
        style = "line hit" if hit else "line"
        rendered.append(f'<div class="{style}"><code>{fragment}</code></div>')
    return "".join(rendered) + "</section>"


def render_http_shot(
    raw_request: str,
    raw_response: str,
    out: Path,
    *,
    highlight: list[str] | None = None,
    title: str = "HTTP exchange",
    allow_fallback: bool = False,
) -> Path:
    columns = [
        ("Request", _exchange_rows(raw_request, [])),
        ("Response", _exchange_rows(raw_response, highlight or [])),
    ]
    body = "".join(_panel(label, rows) for label, rows in columns)
    try:
        return render_png(card(title, f'<div class="content grid">{body}</div>', kind="http"), out)
    except BrowserUnavailable:
        if not allow_fallback:
            raise
        return text_png(title, columns, out)
