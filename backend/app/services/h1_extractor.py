"""Pure H1 record boundary extraction helpers."""

from __future__ import annotations

import re


H1_BOUNDARY = re.compile(r"(?:^|\|\||\r?\n)(H1\|)")


def _h1_record_spans(extra: str) -> list[tuple[int, int]]:
    starts = [match.start(1) for match in H1_BOUNDARY.finditer(extra)]
    spans: list[tuple[int, int]] = []
    for index, start in enumerate(starts):
        boundaries: list[int] = []
        newline = re.search(r"\r?\n", extra[start:])
        if newline is not None:
            boundaries.append(start + newline.start())
        if index + 1 < len(starts):
            next_start = starts[index + 1]
            delimiter_start = next_start - 2 if extra[next_start - 2:next_start] == "||" else next_start - 1
            if delimiter_start > 0 and extra[delimiter_start - 1:delimiter_start] == "\r":
                delimiter_start -= 1
            boundaries.append(delimiter_start)
        end = min(boundaries) if boundaries else len(extra)
        spans.append((start, end))
    return spans


def extract_h1_records(extra: str) -> list[str]:
    """Extract every H1 record from one raw extra value."""
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")

    return [extra[start:end] for start, end in _h1_record_spans(extra)]


def remove_h1_records(extra: str) -> str:
    """Remove H1 records while retaining all non-H1 protocol text."""
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")

    spans = _h1_record_spans(extra)
    if not spans:
        return extra
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.append(extra[cursor:start])
        cursor = end
    parts.append(extra[cursor:])
    return "".join(parts)
