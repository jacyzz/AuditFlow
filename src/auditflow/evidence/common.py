import os
from contextlib import contextmanager
from html import escape
from importlib.resources import files
from io import BytesIO
from pathlib import Path
from string import Template
from typing import Iterator

from PIL import Image, ImageDraw, ImageFont

from auditflow.core.config import DockerSettings
from auditflow.core.paths import atomic_write
from auditflow.environment import validate_isolated_endpoint


class BrowserUnavailable(RuntimeError):
    """The optional Chromium rendering environment is unavailable."""


def _launch_chromium(playwright):
    from playwright.sync_api import Error

    try:
        channel = os.environ.get("AUDITFLOW_CHROMIUM_CHANNEL")
        if channel not in {None, "chrome", "msedge"}:
            raise ValueError("AUDITFLOW_CHROMIUM_CHANNEL must be chrome or msedge")
        return playwright.chromium.launch(
            channel=channel,
            args=["--disable-background-networking"],
        )
    except Error as exc:
        raise BrowserUnavailable(
            "Chromium unavailable. Run: python -m playwright install chromium"
        ) from exc


@contextmanager
def browser_page(width: int, height: int) -> Iterator:
    """Offline sandboxed Chromium context for rendering static HTML evidence cards."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailable(
            "Install Playwright, then run: python -m playwright install chromium"
        ) from exc
    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright)
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2,
                java_script_enabled=False,
                service_workers="block",
            )
            context.route("**/*", lambda route: route.abort())
            yield context.new_page()
        finally:
            browser.close()


@contextmanager
def live_browser_page(
    width: int,
    height: int,
    *,
    settings: DockerSettings,
    cookies: list[dict] | None = None,
    headers: dict[str, str] | None = None,
    proxy: str | None = None,
) -> Iterator:
    """Live isolated Chromium context (JS enabled) restricted strictly to allowed isolated endpoints."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserUnavailable(
            "Install Playwright, then run: python -m playwright install chromium"
        ) from exc

    def _guard_route(route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            route.continue_()
            return
        try:
            validate_isolated_endpoint(url, settings)
        except ValueError:
            route.abort()
            return
        route.continue_()

    with sync_playwright() as playwright:
        browser = _launch_chromium(playwright)
        try:
            context_kwargs: dict = {
                "viewport": {"width": width, "height": height},
                "device_scale_factor": 2,
                "java_script_enabled": True,
                "ignore_https_errors": True,
            }
            if headers:
                context_kwargs["extra_http_headers"] = headers
            if proxy:
                context_kwargs["proxy"] = {"server": proxy}
            context = browser.new_context(**context_kwargs)
            if cookies:
                context.add_cookies(cookies)
            context.route("**/*", _guard_route)
            yield context.new_page()
        finally:
            browser.close()


def card(title: str, body: str, *, kind: str, extra_css: str = "") -> str:
    directory = files("auditflow.evidence").joinpath("templates")
    return Template(directory.joinpath("card.html").read_text(encoding="utf-8")).substitute(
        title=escape(title),
        body=body,
        kind=kind,
        css=directory.joinpath("card.css").read_text(encoding="utf-8") + extra_css,
    )


def render_png(html: str, out: Path) -> Path:
    with browser_page(720, 540) as page:
        page.set_content(html, wait_until="load")
        image = page.locator("main").screenshot(animations="disabled", timeout=10000)
    atomic_write(out, image)
    return out


def text_png(
    title: str,
    columns: list[tuple[str, list[tuple[str, bool]]]],
    out: Path,
) -> Path:
    """Render an offline fallback using the same lines and emphasis as the HTML card."""
    font = _system_font(("msyh.ttc", "NotoSansCJK-Regular.ttc", "DejaVuSansMono.ttf"), 22)
    heading = _system_font(("msyh.ttc", "NotoSansCJK-Regular.ttc", "DejaVuSans.ttf"), 30)
    width = 1440
    gutter = 42
    column_width = (width - 2 * gutter) // len(columns)
    columns_wrapped = []
    for label, rows in columns:
        wrapped = []
        for line, hit in rows:
            limit = max(10, int((column_width - 40) / font.getlength("W")))
            text = line.expandtabs(4)
            wrapped.extend(
                (text[start : start + limit], hit) for start in range(0, max(1, len(text)), limit)
            )
        columns_wrapped.append((label, wrapped))
    height = 178 + 34 * max(len(rows) for _, rows in columns_wrapped)
    if height > 20000:
        raise ValueError("evidence is too long to fit in a PNG; select a shorter excerpt")
    image = Image.new("RGB", (width, height), "#eaf0f6")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 20, width - 20, height - 20), radius=22, fill="#ffffff")
    display_title = title.replace("\r", " ").replace("\n", " ")
    while heading.getlength(display_title) > width - 90:
        display_title = display_title[:-5] + "…"
    draw.text((gutter, 38), display_title, font=heading, fill="#13233b")
    for index, (label, rows) in enumerate(columns_wrapped):
        x = gutter + column_width * index
        draw.text((x + 9, 94), label, font=font, fill="#365a83")
        for row, (line, hit) in enumerate(rows):
            y = 128 + row * 34
            if hit:
                draw.rectangle((x, y - 2, x + column_width - 12, y + 29), fill="#fff0ee")
                draw.rectangle((x, y - 2, x + 4, y + 29), fill="#cc3247")
            draw.text((x + 9, y), line, font=font, fill="#17263c")
    data = BytesIO()
    image.save(data, format="PNG")
    atomic_write(out, data.getvalue())
    return out


def _system_font(names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)
