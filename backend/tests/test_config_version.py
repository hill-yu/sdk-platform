import pytest

from app.services.config_version import max_version, next_version, parse_version


@pytest.mark.parametrize(
    ("current", "expected"),
    [
        (None, "1.0.0"),
        ("1.0.8", "1.0.9"),
        ("1.0.9", "1.1.0"),
        ("1.9.9", "2.0.0"),
    ],
)
def test_next_version_uses_decimal_triplet_sequence(current, expected):
    assert next_version(current) == expected


@pytest.mark.parametrize(
    "value",
    ["1.0", "v1.0.0", "1.0.10", "draft_1", "20260811_v120000", "01.0.0"],
)
def test_parse_version_rejects_non_sequence_values(value):
    with pytest.raises(ValueError, match="非法正式版本"):
        parse_version(value)


def test_max_version_compares_numeric_components():
    assert max_version(["1.9.9", "2.0.0", "1.0.9"]) == "2.0.0"


def test_max_version_returns_none_for_empty_values():
    assert max_version([]) is None
