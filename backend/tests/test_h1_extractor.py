from __future__ import annotations

import pytest

from app.services.h1_extractor import extract_h1_records


def test_extracts_every_h1_without_splitting_plain_double_pipes() -> None:
    extra = "prefix||not-a-record\nH1|t=one|p=1||H1|t=two|p=2\r\nH1|t=three|p=3"

    assert extract_h1_records(extra) == [
        "H1|t=one|p=1",
        "H1|t=two|p=2",
        "H1|t=three|p=3",
    ]


def test_no_h1_returns_empty_list() -> None:
    assert extract_h1_records("ordinary raw log||still raw") == []


def test_rejects_non_string_extra() -> None:
    with pytest.raises(TypeError, match="^extra 必须是字符串$"):
        extract_h1_records(None)  # type: ignore[arg-type]
