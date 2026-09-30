from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.flow_log_decoder import DECODER_VERSION, decode_extra


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flow_log_vectors.json"


@pytest.fixture(scope="module")
def vectors() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_decoder_version_is_stable() -> None:
    assert DECODER_VERSION == "2.0.0"


def test_decode_extra_decodes_representative_h1_vector(vectors: dict[str, Any]) -> None:
    vector = vectors["h1_single"]

    decoded = decode_extra(vector["extra"])

    assert len(decoded) == 1
    for key, value in vector["expected"].items():
        assert decoded[0][key] == value


def test_decode_extra_decodes_multiple_h1_records(vectors: dict[str, Any]) -> None:
    vector = vectors["h1_multiple"]

    decoded = decode_extra(vector["extra"])

    assert [item["config_id"] for item in decoded] == vector["expected_config_ids"]


def test_decode_extra_does_not_overwrite_an_earlier_h1() -> None:
    decoded = decode_extra("H1|i=GC|p=1||H1|i=GD|p=2")

    assert [item["config_id"] for item in decoded] == [1004, 1005]


def test_decode_extra_decodes_legacy_final_flow_result(vectors: dict[str, Any]) -> None:
    vector = vectors["legacy_final_flow_result"]

    decoded = decode_extra(vector["extra"])

    assert len(decoded) == 1
    for key, value in vector["expected"].items():
        assert decoded[0][key] == value


def test_decode_extra_ignores_unknown_formats(vectors: dict[str, Any]) -> None:
    assert decode_extra(vectors["unknown"]["extra"]) == []


def test_decode_extra_tolerates_malformed_fields(vectors: dict[str, Any]) -> None:
    vector = vectors["malformed_fields"]

    decoded = decode_extra(vector["extra"])

    assert len(decoded) == 1
    for key, value in vector["expected"].items():
        assert decoded[0][key] == value


def test_decode_extra_preserves_utf8_and_chinese_display_values(vectors: dict[str, Any]) -> None:
    vector = vectors["chinese_display"]

    decoded = decode_extra(vector["extra"])
    attempt = decoded[0]["planned_click_attempts"][0]

    assert attempt["page_context_result"] == vector["expected"]["page_context_result"]
    assert attempt["completion_status"] == "finish"
    assert attempt["navigation_result"] == vector["expected"]["navigation_result"]
    assert attempt["popup_redirect_result"] == vector["expected"]["popup_redirect_result"]
    assert decoded[0]["interaction_failure_detail"] == vector["expected"]["interaction_failure_detail"]


@pytest.mark.parametrize("value", [None, 42, b"H1|i=GC", ["H1|i=GC"]])
def test_decode_extra_rejects_non_string_input(value: object) -> None:
    with pytest.raises(TypeError, match="^extra 必须是字符串$"):
        decode_extra(value)  # type: ignore[arg-type]


def test_decode_extra_rejects_more_than_maximum_characters() -> None:
    with pytest.raises(ValueError, match="^extra 超过解析长度限制$"):
        decode_extra("x" * 1_000_001)


def test_decode_extra_accepts_exactly_500_records() -> None:
    decoded = decode_extra("\n".join(["H1|i=GC"] * 500))

    assert len(decoded) == 500


def test_decode_extra_rejects_more_than_500_decoded_records() -> None:
    with pytest.raises(ValueError, match="^extra 中记录数超过限制$"):
        decode_extra("\n".join(["H1|i=GC"] * 501))
