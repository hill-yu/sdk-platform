"""按包配置使用的三段十进制版本规则。"""
from __future__ import annotations

import re
from collections.abc import Iterable


VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.([0-9])\.([0-9])$")


def parse_version(value: str) -> tuple[int, int, int]:
    """解析正式版本；minor 和 patch 固定为单个十进制位。"""
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError(f"非法正式版本: {value}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def next_version(current: str | None) -> str:
    """返回序列中的下一版本；空序列从 1.0.0 开始。"""
    if current is None:
        return "1.0.0"
    major, minor, patch = parse_version(current)
    patch += 1
    if patch == 10:
        patch = 0
        minor += 1
    if minor == 10:
        minor = 0
        major += 1
    return f"{major}.{minor}.{patch}"


def max_version(values: Iterable[str]) -> str | None:
    """按数值段返回最大正式版本。"""
    parsed = [(parse_version(value), value) for value in values]
    return max(parsed)[1] if parsed else None
