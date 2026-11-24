from html import escape
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from auditflow.core.config import DockerSettings
from auditflow.core.paths import atomic_write
from auditflow.environment import validate_isolated_endpoint
from auditflow.evidence.common import _system_font, browser_page, live_browser_page

_CSP = (
    '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    "style-src 'unsafe-inline'; img-src data:; font-src data:; "
    'base-uri \'none\'; form-action \'none\'">'
)


def _overlay_address_bar(png_bytes: bytes, address_text: str) -> bytes:
    with Image.open(BytesIO(png_bytes), formats=["PNG"]) as shot:
        width, height = shot.size
        bar_height = 68
        canvas = Image.new("RGB", (width, height + bar_height), "#e6edf5")
        draw = ImageDraw.Draw(canvas)
        draw.rounded_rectangle(
            (20, 12, width - 20, bar_height - 12), radius=12, fill="#ffffff", outline="#c7d3e3"
        )
        font = _system_font(("msyh.ttc", "DejaVuSansMono.ttf", "DejaVuSans.ttf"), 24)
        label = address_text.replace("\r", " ").replace("\n", " ")
        while font.getlength(label) > width - 80 and len(label) > 10:
            label = label[:-4] + "..."
        draw.text((38, 20), label, font=font, fill="#1b2c44")
        canvas.paste(shot, (0, bar_height))
        buf = BytesIO()
        canvas.save(buf, format="PNG")
        return buf.getvalue()


def _is_http_url(value: Path | str) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def capture_web_shot(
    source: Path | str,
    out: Path,
    *,
    show_address_bar: bool = False,
    wait_selector: str | None = None,
    docker_settings: DockerSettings | None = None,
    cookies: list[dict] | None = None,
    headers: dict[str, str] | None = None,
    proxy: str | None = None,
    timeout_ms: int = 15000,
) -> Path:
    """Capture a PNG from either a saved local HTML snapshot or a live isolated HTTP(S) URL."""
    if _is_http_url(source):
        assert isinstance(source, str)
        settings = docker_settings or DockerSettings(enforce_port_range=False)
        validate_isolated_endpoint(source, settings)
        chosen_proxy = proxy if proxy is not None else settings.burp_upstream_proxy
        with live_browser_page(
            1440,
            900,
            settings=settings,
            cookies=cookies,
            headers=headers,
            proxy=chosen_proxy,
        ) as page:
            response = page.goto(source, wait_until="networkidle", timeout=timeout_ms)
            if wait_selector:
                page.locator(wait_selector).first.wait_for(timeout=min(timeout_ms, 8000))
            final_url = page.url
            status_code = response.status if response is not None else None
            data = page.screenshot(full_page=True, animations="disabled", timeout=timeout_ms)
        if show_address_bar:
            prefix = f"[HTTP {status_code}] " if status_code is not None else ""
            data = _overlay_address_bar(data, f"{prefix}{final_url}")
        atomic_write(out, data)
        return out

    source_path = Path(source)
    if source_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("web evidence requires an isolated HTTP(S) URL or an existing local HTML snapshot")
    text = source_path.read_text(encoding="utf-8-sig")
    css = "<style>body{margin:0} #auditflow-source{font:14px sans-serif;padding:12px;background:#edf2fa}</style>"
    bar = (
        f'<div id="auditflow-source">Local snapshot · {escape(source_path.name)}</div>'
        if show_address_bar
        else ""
    )
    html = f"<!doctype html><html><head><meta charset=utf-8>{_CSP}{css}</head><body>{bar}{text}"
    with browser_page(1440, 900) as page:
        page.set_content(html, wait_until="load", timeout=10000)
        if wait_selector:
            page.locator(wait_selector).first.wait_for(timeout=5000)
        data = page.screenshot(full_page=True, animations="disabled", timeout=10000)
    atomic_write(out, data)
    return out
