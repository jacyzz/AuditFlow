import hashlib
import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from openpyxl import load_workbook
from pydantic import HttpUrl, ValidationError

from auditflow.core.config import Platforms
from auditflow.core.schemas import Meta

Source = Literal["github", "gitee", "gitcode"]
_SOURCES: dict[str, Source] = {"github.com": "github", "gitee.com": "gitee", "gitcode.com": "gitcode"}
_ENDPOINTS = {
    "github": "https://api.github.com/search/repositories",
    "gitee": "https://gitee.com/api/v5/search/repositories",
    "gitcode": "https://api.gitcode.com/api/v5/search/repositories",
}
_URL = re.compile(r"https?://[^\s<>\[\]()\"'`]+", re.I)
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def repository_url(value: str) -> tuple[Source, str, list[str]]:
    parsed = urlsplit(value.strip())
    platform = _SOURCES.get(parsed.hostname or "")
    if (
        platform is None or parsed.scheme not in {"https", "http"} or parsed.port is not None
        or parsed.username is not None or parsed.password is not None
    ):
        raise ValueError("expected a GitHub, Gitee or GitCode repository URL")
    path = parsed.path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) < 2 or (len(parts) != 2 and platform != "gitcode"):
        raise ValueError("expected a repository URL, with namespace and repository name")
    if not all(_COMPONENT.fullmatch(part) for part in parts):
        raise ValueError("invalid repository namespace or name")
    return platform, f"https://{parsed.hostname}/{'/'.join(parts)}", parts


def metadata_from_url(value: str, row: dict | None = None) -> Meta:
    platform, url, parts = repository_url(value)
    row = row or {}
    full_name = "/".join(parts).lower()
    digest = hashlib.sha256(full_name.encode()).hexdigest()[:12]
    suffix = re.sub(r"[^a-z0-9]+", "_", full_name)[:90].strip("_")
    homepage = row.get("homepage")
    try:
        homepage_url = HttpUrl(homepage) if homepage else None
        if homepage_url and homepage_url.username is not None:
            homepage_url = None
    except ValidationError:
        homepage_url = None
    license_info = row.get("license")
    if isinstance(license_info, dict):
        license_info = license_info.get("spdx_id")
    return Meta(
        target_id=f"{platform}_{suffix}_{digest}",
        platform=platform,
        repo_url=HttpUrl(url),
        homepage=homepage_url,
        vendor="/".join(parts[:-1]),
        product=row.get("name") or parts[-1],
        description=row.get("description") or "",
        stars=row.get("stargazers_count", row.get("stars_count")),
        primary_language=row.get("language") or None,
        license=license_info or None,
        default_branch=row.get("default_branch") or None,
        scout_profile="metadata-search" if row else "from-list",
    )


def search_projects(
    platform: str, query: str, settings: Platforms, *, limit: int = 10,
    client: httpx.Client | None = None,
) -> list[Meta]:
    if platform not in _ENDPOINTS or not query.strip() or not 1 <= limit <= 100:
        raise ValueError("specify a supported platform, a keyword and a limit between 1 and 100")
    token = os.environ.get(getattr(settings, f"{platform}_token_env"))
    if platform == "gitcode" and not token:
        raise ValueError("GitCode repository search requires its configured token variable")
    if client is None:
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as connection:
            return search_projects(platform, query, settings, limit=limit, client=connection)

    per_page = min(limit, 20) if platform == "gitcode" else limit
    accumulated: dict[str, Meta] = {}
    params = {"q": query.strip(), "per_page": per_page}
    headers = {"Accept": "application/json"}
    if token and platform == "github":
        headers["Authorization"] = f"Bearer {token}"
    elif token:
        params["access_token"] = token
    max_pages = (limit + per_page - 1) // per_page
    for page in range(1, max_pages + 1):
        try:
            response = client.get(
                _ENDPOINTS[platform], params={**params, "page": page},
                headers=headers, follow_redirects=False,
            )
            if not response.is_success:
                raise ValueError(f"{platform} metadata API returned HTTP {response.status_code}")
            payload = response.json()
        except httpx.HTTPError:
            raise ValueError(f"{platform} metadata API request failed") from None
        rows = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError(f"{platform} metadata API returned an unexpected response")
        for row in rows:
            if not isinstance(row, dict) or row.get("private"):
                continue
            url = row.get("html_url") or row.get("web_url") or row.get("http_url_to_repo")
            if not isinstance(url, str):
                continue
            try:
                project = metadata_from_url(url, row)
            except (ValueError, TypeError):
                continue
            if project.platform == platform:
                accumulated.setdefault(project.target_id, project)
        if len(rows) < per_page:
            break
    return list(accumulated.values())[:limit]


def list_urls(path: Path) -> list[str]:
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        workbook = load_workbook(path, read_only=False, data_only=True)
        try:
            cells = (
                cell for sheet in workbook.worksheets for row in sheet.iter_rows() for cell in row
            )
            values = [
                cell.hyperlink.target if cell.hyperlink and cell.hyperlink.target else str(cell.value)
                for cell in cells if cell.hyperlink or isinstance(cell.value, str)
            ]
        finally:
            workbook.close()
    elif path.suffix.lower() in {".md", ".txt", ".csv"}:
        values = [path.read_text(encoding="utf-8-sig")]
    else:
        raise ValueError("import from .txt, .md, .csv, .xlsx or .xlsm")
    return [url.rstrip(".,;") for entry in values for url in _URL.findall(entry)]


def import_projects(path: Path) -> list[Meta]:
    projects = {}
    for url in list_urls(path):
        try:
            project = metadata_from_url(url)
        except ValueError:
            continue
        projects.setdefault(project.target_id, project)
    return list(projects.values())
