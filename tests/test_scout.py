import httpx
import pytest
from openpyxl import Workbook


@pytest.mark.parametrize(
    ("platform", "host", "endpoint", "url"),
    [
        ("github", "api.github.com", "/search/repositories", "https://github.com/Example/Repo"),
        ("gitee", "gitee.com", "/api/v5/search/repositories", "https://gitee.com/Example/Repo"),
        ("gitcode", "api.gitcode.com", "/api/v5/search/repositories",
         "https://gitcode.com/Example/Repo"),
    ],
)
def test_metadata_search_normalizes_platform_response(platform, host, endpoint, url, monkeypatch):
    from auditflow.core.config import Platforms
    from auditflow.scout.platforms import search_projects

    def respond(request):
        assert request.method == "GET"
        assert request.url.host == host and request.url.path == endpoint
        assert request.url.params["q"] == "documentation"
        item = {"html_url": url, "name": "Demo", "description": None, "stargazers_count": 4}
        payload = {"items": [item]} if platform == "github" else [item]
        return httpx.Response(200, json=payload)

    monkeypatch.setenv("GITCODE_TOKEN", "fixture-token")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        results = search_projects(platform, "documentation", Platforms(), client=client)
    assert len(results) == 1
    assert results[0].product == "Demo"
    assert results[0].stars == 4 and results[0].commit_sha is None


def test_excel_and_sqlite_dedup_normalize_urls(tmp_path):
    from auditflow.core.state import Tracker
    from auditflow.scout.dedup import save_new_projects
    from auditflow.scout.platforms import import_projects

    path = tmp_path / "repo-list.md"
    path.write_text(
        "[Old](https://github.com/Example/old)\n"
        "[New](https://gitee.com/team/new.git)\nhttps://GITEE.com/TEAM/NEW/\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.xlsx"
    workbook = Workbook()
    workbook.active["A1"].hyperlink = "https://github.com/example/OLD/"
    workbook.save(history)
    projects = import_projects(path)
    assert len(projects) == 2
    tracker = Tracker(tmp_path / "tracker.sqlite")
    accepted = save_new_projects(projects, tracker, tmp_path / "workspaces", history=history)
    assert [item.product for item in accepted] == ["new"]
    assert save_new_projects(projects, tracker, tmp_path / "workspaces", history=history) == []


def test_failed_later_project_does_not_orphan_earlier_metadata(tmp_path):
    from auditflow.core.state import Tracker
    from auditflow.scout.dedup import save_new_projects
    from auditflow.scout.platforms import metadata_from_url

    projects = [
        metadata_from_url("https://gitee.com/example/one"),
        metadata_from_url("https://gitee.com/example/two"),
    ]
    workspaces = tmp_path / "workspaces"
    existing = workspaces / projects[1].target_id / "meta.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("manual content", encoding="utf-8")
    tracker = Tracker(tmp_path / "tracker.sqlite")
    with pytest.raises(ValueError, match="untracked"):
        save_new_projects(projects, tracker, workspaces)
    assert tracker.target_status(projects[0].target_id) == "DISCOVERED"
    existing.unlink()
    assert save_new_projects(projects, tracker, workspaces) == projects[1:]
