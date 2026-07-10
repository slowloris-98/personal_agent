import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.docs_writer import _week_title  # noqa: E402
from personal_agent.markdown_to_docs import build_day_requests  # noqa: E402

PLAN = """\
### Top priorities
- Ship the **release**
- Review PR

### Watch / urgent
Nothing urgent."""


def _by_key(requests, key):
    return [r[key] for r in requests if key in r]


def test_first_request_inserts_marker_stripped_text():
    requests = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=False)
    insert = requests[0]["insertText"]
    assert insert["location"]["index"] == 1
    text = insert["text"]
    assert "###" not in text
    assert "**" not in text
    assert "Top priorities" in text
    assert "release" in text
    assert text.startswith("2026-07-06 — Daily Plan\n")


def test_title_and_headings_get_paragraph_styles():
    requests = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=False)
    styles = [p["paragraphStyle"]["namedStyleType"] for p in _by_key(requests, "updateParagraphStyle")]
    # Day title + two "###" headings.
    assert styles[0] == "TITLE"
    assert styles.count("HEADING_2") == 2


def test_contiguous_bullets_merge_into_one_request():
    requests = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=False)
    bullets = _by_key(requests, "createParagraphBullets")
    assert len(bullets) == 1
    assert bullets[0]["bulletPreset"] == "BULLET_DISC_CIRCLE_SQUARE"


def test_bold_range_covers_the_unmarked_word():
    requests = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=False)
    text = requests[0]["insertText"]["text"]
    bolds = _by_key(requests, "updateTextStyle")
    assert len(bolds) == 1
    rng = bolds[0]["range"]
    assert bolds[0]["textStyle"]["bold"] is True
    # insert_index is 1, so absolute index i maps to text[i - 1].
    assert text[rng["startIndex"] - 1 : rng["endIndex"] - 1] == "release"


def test_page_break_only_when_requested():
    without = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=False)
    assert not _by_key(without, "insertPageBreak")

    with_break = build_day_requests("2026-07-06", PLAN, insert_index=1, add_page_break=True)
    breaks = _by_key(with_break, "insertPageBreak")
    assert len(breaks) == 1
    # Sits just past the inserted block.
    text_len = len(with_break[0]["insertText"]["text"])
    assert breaks[0]["location"]["index"] == 1 + text_len


def test_week_title_format_and_year_boundary():
    assert re.fullmatch(r"Daily Plans — \d{4}-W\d{2}", _week_title("2026-07-06"))
    # 2025-12-29 (Mon) belongs to ISO week 2026-W01.
    assert _week_title("2025-12-29") == "Daily Plans — 2026-W01"
