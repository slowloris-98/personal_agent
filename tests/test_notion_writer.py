import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import notion_writer  # noqa: E402

TOKEN = "secret-token"
ROOT = "root-page-id"
PLAN = "### Top priorities\n- Ship the **release**"


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.ok = True
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


class FakeNotion:
    """Records POST/PATCH calls and hands back incrementing page ids."""

    def __init__(self):
        self.posts = []
        self.patches = []
        self._counter = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self._counter += 1
        self.posts.append({"url": url, "headers": headers, "body": json})
        return FakeResponse({"id": f"page-{self._counter}"})

    def patch(self, url, headers=None, json=None, timeout=None):
        self.patches.append({"url": url, "headers": headers, "body": json})
        return FakeResponse({"id": url.rsplit("/", 2)[-2]})


@pytest.fixture
def notion(tmp_path, monkeypatch):
    fake = FakeNotion()
    monkeypatch.setattr(notion_writer, "requests", fake)
    monkeypatch.setattr(notion_writer, "CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(notion_writer, "_STATE_PATH", tmp_path / "notion_state.json")
    return fake


def test_first_run_creates_week_then_day_page(notion):
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", PLAN)

    assert len(notion.posts) == 2
    week_post, day_post = notion.posts

    # Week page: created under the root, title only, no markdown body.
    assert week_post["body"]["parent"]["page_id"] == ROOT
    assert "markdown" not in week_post["body"]
    assert "Week 2026-W28" in _title(week_post)

    # Day page: created under the freshly created week page, carries the plan.
    assert day_post["body"]["parent"]["page_id"] == "page-1"
    assert day_post["body"]["markdown"] == PLAN
    assert "2026-07-06 Monday" == _title(day_post)


def test_second_day_reuses_cached_week_page(notion):
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", PLAN)  # Monday
    notion.posts.clear()
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-07", PLAN)  # Tuesday, same ISO week

    # Only the day page is created; the weekly page is reused from state.
    assert len(notion.posts) == 1
    day_post = notion.posts[0]
    assert day_post["body"]["parent"]["page_id"] == "page-1"  # cached week page
    assert "2026-07-07 Tuesday" == _title(day_post)


def test_rerun_same_day_replaces_content_without_new_page(notion):
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", PLAN)
    notion.posts.clear()
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", "### Updated\n- new")

    assert notion.posts == []  # no new pages created
    assert len(notion.patches) == 1
    patch = notion.patches[0]
    assert patch["url"].endswith("/pages/page-2/markdown")
    assert patch["body"]["type"] == "replace_content"
    assert patch["body"]["replace_content"]["new_str"] == "### Updated\n- new"


def test_headers_carry_token_and_version(notion):
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", PLAN)
    headers = notion.posts[0]["headers"]
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Notion-Version"] == notion_writer._NOTION_VERSION


def test_state_persists_across_calls(notion, tmp_path):
    notion_writer.write_plan(TOKEN, ROOT, "2026-07-06", PLAN)
    state = __import__("json").loads((tmp_path / "notion_state.json").read_text())
    assert state["Week 2026-W28"]["page_id"] == "page-1"
    assert state["Week 2026-W28"]["days"]["2026-07-06"] == "page-2"


def test_missing_token_or_root_raises(notion):
    with pytest.raises(ValueError):
        notion_writer.write_plan("", ROOT, "2026-07-06", PLAN)
    with pytest.raises(ValueError):
        notion_writer.write_plan(TOKEN, "", "2026-07-06", PLAN)


def _title(post) -> str:
    return post["body"]["properties"]["title"]["title"][0]["text"]["content"]
