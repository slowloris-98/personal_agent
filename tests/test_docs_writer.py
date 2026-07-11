import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from personal_agent import docs_writer  # noqa: E402

LABEL = "acct1"
FOLDER_NAME = "Daily Plans"
FOLDER_ID = "fixed-folder-id"
DATE = "2026-07-06"
PLAN = "### Top priorities\n- Ship the **release**"

_DOC_MIME = docs_writer._DOC_MIME
_FOLDER_MIME = docs_writer._FOLDER_MIME


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeFiles:
    def __init__(self, drive):
        self.drive = drive

    def list(self, q=None, spaces=None, fields=None):
        self.drive.list_queries.append(q)
        result = self.drive.list_results.pop(0) if self.drive.list_results else []
        return _Exec({"files": result})

    def create(self, body=None, media_body=None, fields=None):
        self.drive._counter += 1
        file_id = f"id-{self.drive._counter}"
        self.drive.creates.append({"body": body, "media": media_body})
        return _Exec({"id": file_id})

    def update(self, fileId=None, media_body=None):
        self.drive.updates.append({"fileId": fileId, "media": media_body})
        return _Exec({"id": fileId})


class FakeDrive:
    """Records files().list/create/update calls; `list_results` is a queue of the
    `files` array each successive list() call should return."""

    def __init__(self, list_results):
        self.list_results = list(list_results)
        self.list_queries = []
        self.creates = []
        self.updates = []
        self._counter = 0
        self._files = FakeFiles(self)

    def files(self):
        return self._files


@pytest.fixture
def drive(monkeypatch):
    fake = FakeDrive([])

    def _fake_get_service(label, api, version):
        assert (api, version) == ("drive", "v3")
        return fake

    monkeypatch.setattr(docs_writer, "get_service", _fake_get_service)
    return fake


def _media_text(media) -> str:
    return media.getbytes(0, media.size()).decode("utf-8")


def test_daily_title_format():
    assert docs_writer._daily_title("2026-07-06") == "2026-07-06 — Daily Plan"


def test_create_new_doc_with_folder_name(drive):
    # First list() -> folder not found (so it's created); second -> doc not found.
    drive.list_results = [[], []]

    doc_id = docs_writer.write_day_doc(LABEL, "", FOLDER_NAME, DATE, PLAN)

    # Two creates: the owned folder, then the day's Doc inside it.
    assert len(drive.creates) == 2
    folder_create, doc_create = drive.creates
    assert folder_create["body"]["mimeType"] == _FOLDER_MIME
    assert folder_create["media"] is None

    assert doc_create["body"]["mimeType"] == _DOC_MIME
    assert doc_create["body"]["name"] == "2026-07-06 — Daily Plan"
    assert doc_create["body"]["parents"] == ["id-1"]  # the folder just created
    assert doc_create["media"].mimetype() == "text/markdown"
    assert _media_text(doc_create["media"]) == PLAN
    assert doc_id == "id-2"


def test_folder_id_short_circuits_folder_name(drive):
    # Only the doc lookup runs; the folder is taken verbatim (no folder lookup).
    drive.list_results = [[]]

    docs_writer.write_day_doc(LABEL, FOLDER_ID, "ignored-name", DATE, PLAN)

    assert len(drive.list_queries) == 1  # no get_or_create_folder lookup
    assert len(drive.creates) == 1  # no folder created
    doc_create = drive.creates[0]
    assert doc_create["body"]["parents"] == [FOLDER_ID]


def test_rerun_same_day_replaces_existing_doc(drive):
    drive.list_results = [[{"id": "doc-1", "name": "2026-07-06 — Daily Plan"}]]

    doc_id = docs_writer.write_day_doc(LABEL, FOLDER_ID, FOLDER_NAME, DATE, "### Updated\n- new")

    assert drive.creates == []  # nothing new created
    assert len(drive.updates) == 1
    update = drive.updates[0]
    assert update["fileId"] == "doc-1"
    assert update["media"].mimetype() == "text/markdown"
    assert _media_text(update["media"]) == "### Updated\n- new"
    assert doc_id == "doc-1"


def test_missing_folder_config_raises(drive):
    with pytest.raises(ValueError):
        docs_writer.write_day_doc(LABEL, "", "", DATE, PLAN)
