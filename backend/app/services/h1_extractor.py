"""Pure H1 record boundary extraction helpers."""

from __future__ import annotations

import re


H1_BOUNDARY = re.compile(r"(?:^|\|\||\r?\n)(H1\|)")


def extract_h1_records(extra: str) -> list[str]:
    """Extract every H1 record from one raw extra value."""
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")

    starts = [match.start(1) for match in H1_BOUNDARY.finditer(extra)]
    records: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(extra)
        record = extra[start:end].rstrip("|\r\n")
        if record.startswith("H1|"):
            records.append(record)
    return records
