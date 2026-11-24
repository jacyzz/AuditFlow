import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

FIXTURES = Path(__file__).parent / "fixtures"


def test_code_and_transcripts_escape_untrusted_markup(monkeypatch, tmp_path):
    from auditflow.evidence import code_shot, http_shot, term_shot

    pages = []
    for module in (code_shot, http_shot, term_shot):
        monkeypatch.setattr(module, "render_png", lambda html, out: pages.append(html))
    out = tmp_path / "shot.png"
    code_shot.render_code_shot(FIXTURES / "repo" / "policy.py", 1, 3, out, highlight=[2])
    http_shot.render_http_shot("GET /health HTTP/1.1", "HTTP/1.1 200 OK\n\n<script>", out,
                               highlight=["200 OK"])
    term_shot.render_term_shot("pytest", "\x1b[31m<ok>\x1b[0m", out, highlight=["<ok>"])
    assert 'data-line="2"' in pages[0] and 'class="line hit"' in pages[0]
    assert "&lt;script&gt;" in pages[1] and "<script>" not in pages[1]
    assert "&lt;ok&gt;" in pages[2] and "\x1b" not in pages[2]


def test_web_shot_requires_a_local_html_file(tmp_path):
    from auditflow.evidence.web_shot import capture_web_shot

    with pytest.raises((ValueError, FileNotFoundError)):
        capture_web_shot("https://example.invalid/", tmp_path / "web.png")


def test_code_highlighting_keeps_leading_blank_source_lines(monkeypatch, tmp_path):
    from auditflow.evidence import code_shot

    source = tmp_path / "policy.py"
    source.write_text("def policy():\n\n    return True\n", encoding="utf-8")
    rendered = []
    monkeypatch.setattr(code_shot, "render_png", lambda html, out: rendered.append(html))
    code_shot.render_code_shot(source, 2, 3, tmp_path / "code.png", highlight=[3])
    assert 'data-line="2"><span class="number">2</span><code></code>' in rendered[0]
    assert 'class="line hit" data-line="3"' in rendered[0]
    assert ">return<" in rendered[0].split('data-line="3"')[1]


def test_actual_browser_capture_when_available(tmp_path):
    from PIL import Image

    from auditflow.evidence.common import BrowserUnavailable
    from auditflow.evidence.web_shot import capture_web_shot

    html = tmp_path / "page.html"
    html.write_text("<h1>Fixture</h1>", encoding="utf-8")
    out = tmp_path / "page.png"
    try:
        capture_web_shot(html, out)
    except BrowserUnavailable as exc:
        assert "playwright install chromium" in str(exc)
        if os.environ.get("AUDITFLOW_REQUIRE_BROWSER") == "1":
            raise
        pytest.skip(str(exc))
    with Image.open(out) as image:
        assert image.size[0] >= 1440


def test_saved_http_step_can_render_from_cli(tmp_path):
    from PIL import Image

    from auditflow.cli import app

    out = tmp_path / "http.png"
    result = CliRunner().invoke(
        app, ["http-shot", str(FIXTURES / "verify.json"), "1", str(out)]
    )
    assert result.exit_code == 0, result.output
    with Image.open(out) as image:
        assert image.width == 1440
