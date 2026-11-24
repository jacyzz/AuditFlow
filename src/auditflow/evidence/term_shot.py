import re
from html import escape
from pathlib import Path

from auditflow.evidence.common import BrowserUnavailable, card, render_png, text_png

_ESCAPE = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")


def strip_terminal_formatting(text: str) -> str:
    return _ESCAPE.sub("", text)


def render_term_shot(
    command: str,
    stdout: str,
    out: Path,
    *,
    highlight: list[str] | None = None,
    title: str = "Terminal output",
    cwd: str | None = None,
    exit_code: int | None = None,
    allow_fallback: bool = False,
) -> Path:
    prompt = f"{cwd} $ " if cwd else "$ "
    lines = strip_terminal_formatting(f"{prompt}{command}\n{stdout}").splitlines()
    if exit_code is not None:
        lines.append(f"Exit code: {exit_code}")
    rows = [(line, any(pattern in line for pattern in highlight or ())) for line in lines]
    html = []
    for line, hit in rows:
        style = "line hit" if hit else "line"
        html.append(f'<div class="{style}"><code>{escape(line)}</code></div>')
    body = '<section class="content"><h2>Transcript</h2>' + "".join(html) + "</section>"
    try:
        return render_png(card(title, body, kind="term"), out)
    except BrowserUnavailable:
        if not allow_fallback:
            raise
        return text_png(title, [("Transcript", rows)], out)
