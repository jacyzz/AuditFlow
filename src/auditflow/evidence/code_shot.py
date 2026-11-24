from html import escape
from pathlib import Path

from pygments import highlight as pygments_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

from auditflow.evidence.common import BrowserUnavailable, card, render_png, text_png


def code_excerpt(file: Path, start: int, end: int, context: int = 0) -> tuple[int, list[str]]:
    lines = file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if not 1 <= start <= end <= len(lines) or context < 0:
        raise ValueError(f"invalid source line range for {file.name}: {start}–{end}")
    first = max(1, start - context)
    return first, lines[first - 1:end + context]


def render_code_shot(
    file: Path,
    start: int,
    end: int,
    out: Path,
    *,
    highlight: list[int] | None = None,
    label: str | None = None,
    context: int = 0,
    allow_fallback: bool = False,
) -> Path:
    first, lines = code_excerpt(file, start, end, context)
    try:
        lexer = get_lexer_for_filename(file.name, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    formatter = HtmlFormatter(nowrap=True, style="friendly")
    marked = set(highlight or ())
    title = label or f"{file.name}:{start}–{end}"
    rendered = pygments_highlight("\n".join(lines), lexer, formatter).splitlines()
    rows = []
    for offset, line in enumerate(lines):
        number = first + offset
        fragment = rendered[offset] if offset < len(rendered) else escape(line)
        style = "line hit" if number in marked else "line"
        rows.append(
            f'<div class="{style}" data-line="{number}"><span class="number">{number}</span>'
            f"<code>{fragment}</code></div>"
        )
    html = card(
        title,
        '<section class="content">' + "".join(rows) + "</section>",
        kind="code",
        extra_css=formatter.get_style_defs(),
    )
    try:
        return render_png(html, out)
    except BrowserUnavailable:
        if not allow_fallback:
            raise
        numbered = [
            (f"{number:>4}  {line}", number in marked)
            for number, line in enumerate(lines, first)
        ]
        return text_png(title, [("SOURCE", numbered)], out)
