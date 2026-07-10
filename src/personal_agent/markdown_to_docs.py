"""Convert a day's Markdown plan into Google Docs API `batchUpdate` requests.

The Docs API has no "insert Markdown" request — `insertText` inserts literal
text. To get native headings, bold and bullets we insert the marker-stripped
text and then apply paragraph/character styles over the correct index ranges.
Every range stays inside the freshly inserted block (which is prepended at the
top of the doc), so the arithmetic is self-contained and stable.

Docs API indices are counted in UTF-16 code units, so all offset math uses
`_u16len` rather than `len` (they differ only for astral characters, e.g. emoji).
"""
from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

# Markdown heading level -> Docs named paragraph style. The day title gets TITLE.
_HEADING_STYLES = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_2", 4: "HEADING_3"}


def _u16len(text: str) -> int:
    """Length of `text` in UTF-16 code units (the Docs API index unit)."""
    return len(text.encode("utf-16-le")) // 2


def _strip_bold(content: str) -> tuple[str, list[tuple[int, int]]]:
    """Remove ``**bold**`` markers.

    Returns the display text and the ``(start, end)`` spans of the bolded ranges
    in UTF-16 units relative to the start of the display text.
    """
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0  # UTF-16 offset into the display text built so far
    last = 0
    for m in _BOLD_RE.finditer(content):
        before = content[last : m.start()]
        out.append(before)
        pos += _u16len(before)
        inner = m.group(1)
        start = pos
        out.append(inner)
        pos += _u16len(inner)
        spans.append((start, pos))
        last = m.end()
    out.append(content[last:])
    return "".join(out), spans


def _merge_runs(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge adjacent ``(start, end)`` ranges (where one ends where the next
    begins) into single ranges — used to bullet a contiguous block at once."""
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and merged[-1][1] == start:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def build_day_requests(
    date: str,
    plan_markdown: str,
    insert_index: int,
    add_page_break: bool,
) -> list[dict]:
    """Build the Docs `batchUpdate` requests to prepend one formatted day.

    Inserts a titled, formatted block at ``insert_index`` (the top of the body,
    index 1). When ``add_page_break`` is true a page break is appended after the
    block so the previous day is pushed onto its own page.
    """
    # Classify each source line into (kind, heading level, display text, bold spans).
    parsed: list[tuple[str, int, str, list[tuple[int, int]]]] = []
    parsed.append(("title", 0, f"{date} — Daily Plan", []))
    parsed.append(("blank", 0, "", []))
    for raw in plan_markdown.strip().splitlines():
        line = raw.rstrip()
        heading = _HEADING_RE.match(line)
        if heading:
            display, spans = _strip_bold(heading.group(2))
            parsed.append(("heading", len(heading.group(1)), display, spans))
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            display, spans = _strip_bold(bullet.group(1))
            parsed.append(("bullet", 0, display, spans))
            continue
        display, spans = _strip_bold(line)
        parsed.append(("normal" if display else "blank", 0, display, spans))

    # Build the text and collect styling with absolute indices.
    text_parts: list[str] = []
    offset = insert_index  # absolute index where the next line's text starts
    para_styles: list[tuple[int, int, str]] = []  # (start, end, named style)
    bold_reqs: list[tuple[int, int]] = []
    bullet_lines: list[tuple[int, int]] = []  # (start, end) per bullet paragraph

    for kind, level, display, spans in parsed:
        start = offset
        line_text = display + "\n"
        text_parts.append(line_text)
        end = start + _u16len(line_text)  # includes the trailing newline

        if kind == "title":
            para_styles.append((start, end, "TITLE"))
        elif kind == "heading":
            para_styles.append((start, end, _HEADING_STYLES.get(level, "HEADING_3")))
        elif kind == "bullet":
            bullet_lines.append((start, end))

        for span_start, span_end in spans:
            bold_reqs.append((start + span_start, start + span_end))

        offset = end

    full_text = "".join(text_parts)

    # Order matters: only insertText and the trailing page break shift indices,
    # and both act at the block's ends, so the style ranges stay valid.
    requests: list[dict] = [
        {"insertText": {"location": {"index": insert_index}, "text": full_text}}
    ]

    for start, end, style in para_styles:
        requests.append(
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType",
                }
            }
        )

    for start, end in bold_reqs:
        requests.append(
            {
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            }
        )

    for start, end in _merge_runs(bullet_lines):
        requests.append(
            {
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            }
        )

    if add_page_break:
        requests.append(
            {"insertPageBreak": {"location": {"index": insert_index + _u16len(full_text)}}}
        )

    return requests
