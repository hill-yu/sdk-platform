"""Pure decoder for compact flow logs.

The parsing core and dictionaries are extracted from the verified standalone
decoder. This module intentionally performs no external I/O.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from app.services.h1_extractor import extract_h1_records, remove_h1_records


DECODER_VERSION = "2.0.0"
MAX_EXTRA_LENGTH = 1_000_000
MAX_RECORDS_PER_EXTRA = 500

TARGET_AREA_MAP = {
    "b": "banner",
    "a": "anchoredAdvertisement",
    "s": "secondaryPageEntry",
    "n": "none",
}

SELECTED_LABEL_MAP = {
    "b": "BANNER",
    "a": "ANCHORED",
    "s": "SECONDARY",
    "i": "SECONDARY_INTERRUPT",
    "o": "INTERSTITIAL_ACTION_OCR",
    "c": "INTERSTITIAL_CONTINUE",
    "d": "INTERSTITIAL_DIALOG",
    "n": "none",
}

FINAL_REASON_MAP = {
    "l": "load-timeout",
    "x": "home-page-load-failed",
    "t": "total-time-timeout",
    "p": "planned-click-count-exhausted",
    "f": "landing-page-flow-completed",
    "m": "macro-actual-click-limit-reached",
    "i": "indexp-closed",
    "g": "app-entered-background",
    "e": "interaction-execution-failed",
}

INTERACTION_FAILURE_REASON_MAP = {
    "0": "interaction-execution-failed:unknown",
    "1": "interaction-execution-failed:snapshot-invalid-crop-rect",
    "2": "interaction-execution-failed:snapshot-capture-or-crop",
    "3": "interaction-execution-failed:ocr-image-recognition",
    "4": "interaction-execution-failed:dom-snapshot-unavailable",
    "5": "interaction-execution-failed:dom-snapshot-decode",
    "6": "interaction-execution-failed:click",
    "7": "interaction-execution-failed:scroll",
    "8": "interaction-execution-failed:transition-monitor",
    "9": "interaction-execution-failed:webview-or-evaluator-released",
    "A": "interaction-execution-failed:invalid-javascript-result",
    "B": "interaction-execution-failed:network-or-navigation",
    "C": "interaction-execution-failed:interstitial-rect",
    "D": "interaction-execution-failed:configuration-or-parameter",
    "E": "interaction-execution-failed:click-target-state",
    "F": "interaction-execution-failed:flow-state",
    "G": "interaction-execution-failed:ocr-candidate",
    "H": "interaction-execution-failed:dom-candidate",
}

RUNTIME_MODE_MAP = {"r": "randomConfigurationTest", "n": "normal"}

PLANNED_TARGET_KIND_MAP = {
    "b": "banner",
    "a": "anchored",
    "w": "web_element",
    "n": "none",
}

COMPACT_CLICK_REASON_MAP = {
    "0": "other",
    "1": "clicked",
    "2": "target-out-of-viewport",
    "3": "no-hit-target",
    "4": "no-action-target",
    "5": "detached-target",
    "6": "target-not-visible",
    "7": "target-disabled",
    "8": "iframe-hit-target",
    "9": "javascript-error",
    "A": "nil",
    "B": "click-threw-error",
    "C": "network-fluctuation",
    "D": "app-entered-background",
    "E": "jump-succeeded-page-load-failed",
    "F": "platform-jump-link",
    "G": "no-ad-region-found",
}

CLICK_NAVIGATION_CODE_MAP = {
    0: "点击后未跳转",
    1: "点击后跳转",
    2: "未完整走完点击链路",
    3: "因网络波动跳转失败",
    4: "因应用进入后台中断",
    5: "跳转成功，页面加载失败",
    6: "跳转失败，为平台跳转链接",
}

PAGE_CONTEXT_MAP = {"h": "home", "s": "secondary", "n": ""}
ATTEMPT_COMPLETION_STATUS_MAP = {"f": "finish", "p": "pending"}
POPUP_REDIRECT_SOURCE_MAP = {
    "n": "none",
    "c": "createWebViewWith",
    "d": "decidePolicy",
    "cd": "createWebViewWith+decidePolicy",
    "dc": "decidePolicy+createWebViewWith",
}
PAGE_CONTEXT_DISPLAY_MAP = {"home": "首页", "secondary": "次级页面"}

CLICK_STATUS_MAP = {
    "0": "not_clicked",
    "1": "clicked",
    "not_clicked": "not_clicked",
    "clicked": "clicked",
}

MONITOR_STATUS_MAP = {
    "0": "monitor_not_started",
    "1": "monitor_start_failed",
    "2": "monitor_result_failed",
    "3": "monitor_result_invalid",
    "4": "monitor_completed_no_change",
    "5": "monitor_completed_changed",
    "monitor_not_started": "monitor_not_started",
    "monitor_start_failed": "monitor_start_failed",
    "monitor_result_failed": "monitor_result_failed",
    "monitor_result_invalid": "monitor_result_invalid",
    "monitor_completed_no_change": "monitor_completed_no_change",
    "monitor_completed_changed": "monitor_completed_changed",
}

LEGACY_COMPACT_FIELD_MAP = {
    "1": "url",
    "9": "ads",
    "12": "click",
    "1b": "monitor",
    "1s": "timestamp",
    "1w": "load_ms",
    "1x": "inspect_target_ms",
    "1y": "ocr_click_ms",
    "1z": "tail_ms",
    "20": "duration_ms",
    "i": "selected",
    "cc": "ads",
    "clk": "click",
    "res": "monitor",
    "dur_ms": "duration_ms",
    "load_ms": "load_ms",
    "inspect_target_ms": "inspect_target_ms",
    "ocr_click_ms": "ocr_click_ms",
    "tail_ms": "tail_ms",
    "u": "url",
    "ts": "timestamp",
    "date": "timestamp",
    "dt": "timestamp",
    "bx": "bxof",
    "pm": "PmLH",
    "hc": "home_click_target",
    "j": "page_jump",
    "ic": "interstitial_click",
    "it": "interstitial_click_target",
}

MODERN_COMPACT_FIELD_MAP = {
    "t": "compact_timestamp",
    "i": "url",
    "b": "bxof",
    "p": "PmLH",
    "h": "home_click_target",
    "j": "page_jump",
    "x": "interstitial_click",
    "r": "interstitial_click_target",
    "a": "ads",
    "s": "selected",
    "k": "compact_status",
    "u": "duration_ms",
}

HOST_FINAL_RESULT_FIELD_MAP = {
    "t": "compact_timestamp",
    "w": "window",
    "i": "config_id",
    "b": "bxof",
    "bx": "bxof",
    "p": "expected_click_count",
    "c": "expected_click_count_clone",
    "iv": "interstitial_presentation_count",
    "ic": "interstitial_click_count",
    "iz": "interstitial_close_count",
    "pa": "planned_click_attempts",
    "a": "target_area",
    "s": "selected_label",
    "r": "final_reason",
    "u": "duration_ms",
    "om": "online_minutes",
    "ol": "matched_olt",
    "ap": "ads_probability",
    "as": "ads_probability_source",
    "bk": "Bkrf",
    "ip": "IDP",
    "ih": "IDP_hit",
    "qz": "qz",
    "hp": "Hpdg",
    "hm": "remain_hpdg",
    "db": "daily_bxof_open_count",
    "lv": "ltjTV_values",
    "jv": "Jbgw_ms_values",
    "tt": "total_timeout_s",
    "ts": "total_time_source",
    "m": "runtime_mode",
    "k": "sample_kind",
    "sk": "sample_kind",
    "h": "home_page_flags",
    "hd": "home_page_did_finish",
    "hj": "home_page_js_ready",
    "ht": "home_page_load_timeout",
    "hl": "home_page_load_failed",
    "hc": "home_page_web_content_process_terminated",
    "hn": "home_page_web_content_process_terminated_link",
    "cm": "home_page_did_commit",
    "cl": "home_page_did_commit_link",
    "rs": "home_page_ready_reason",
    "hu": "home_page_url",
    "ed": "interaction_failure_detail",
    "ct": "interstitial_tracking",
}

HOME_PAGE_READY_REASON_MAP = {
    "wl": "window-load",
    "ac": "already-complete",
    "window-load": "window-load",
    "already-complete": "already-complete",
}
ADS_PROBABILITY_SOURCE_MAP = {"b": "BCRT", "t": "tkE", "n": "none"}
TOTAL_TIME_SOURCE_MAP = {"w": "WLCE", "u": "Uvwa", "n": "none"}
SAMPLE_KIND_MAP = {
    "a": "ads_probability_sample",
    "t": "total_time_sample",
    "hf": "home_page_did_finish",
    "hr": "home_page_js_ready",
    "hfhr": "home_page_did_finish+home_page_js_ready",
    "n": "none",
}

READABLE_RE = re.compile(r"^FINAL_FLOW_RESULT\|(?:ts|date)=(?P<ts>[^|]+)\|(?P<body>.+)$")


@dataclass
class DecodedFlowSummary:
    source_type: str
    raw: str
    timestamp: Optional[str] = None
    url: Optional[str] = None
    bxof: Optional[str] = None
    PmLH: Optional[int] = None
    ads: Optional[int] = None
    selected: Optional[str] = None
    click: Optional[str] = None
    home_click_target: Optional[str] = None
    page_jump: Optional[str] = None
    interstitial_click: Optional[str] = None
    interstitial_click_target: Optional[str] = None
    monitor: Optional[str] = None
    duration_ms: Optional[int] = None
    load_ms: Optional[int] = None
    inspect_target_ms: Optional[int] = None
    ocr_click_ms: Optional[int] = None
    tail_ms: Optional[int] = None
    window: Optional[str] = None
    config_id: Optional[int] = None
    expected_click_count: Optional[int] = None
    expected_click_count_clone: Optional[int] = None
    interstitial_presentation_count: Optional[int] = None
    interstitial_click_count: Optional[int] = None
    interstitial_close_count: Optional[int] = None
    interstitial_tracking: Optional[str] = None
    planned_click_attempts: List[Dict[str, object]] = field(default_factory=list)
    target_area: Optional[str] = None
    selected_label: Optional[str] = None
    final_reason: Optional[str] = None
    runtime_mode: Optional[str] = None
    online_minutes: Optional[int] = None
    matched_olt: Optional[int] = None
    ads_probability: Optional[float] = None
    ads_probability_source: Optional[str] = None
    Bkrf: Optional[float] = None
    IDP: Optional[float] = None
    IDP_hit: Optional[str] = None
    qz: Optional[float] = None
    Hpdg: Optional[int] = None
    remain_hpdg: Optional[int] = None
    daily_bxof_open_count: Optional[int] = None
    ltjTV_values: List[int] = field(default_factory=list)
    Jbgw_ms_values: List[int] = field(default_factory=list)
    total_timeout_s: Optional[int] = None
    total_time_source: Optional[str] = None
    sample_kind: Optional[str] = None
    home_page_did_finish: Optional[str] = None
    home_page_js_ready: Optional[str] = None
    home_page_load_timeout: Optional[str] = None
    home_page_load_failed: Optional[str] = None
    home_page_web_content_process_terminated: Optional[str] = None
    home_page_web_content_process_terminated_link: Optional[str] = None
    home_page_did_commit: Optional[str] = None
    home_page_did_commit_link: Optional[str] = None
    home_page_ready_reason: Optional[str] = None
    home_page_url: Optional[str] = None
    protocol_version: Optional[str] = None
    sequence: Optional[str] = None
    event_code: Optional[str] = None
    extra_fields: Dict[str, str] = field(default_factory=dict)
    interaction_failure_detail: Optional[str] = None


def parse_numeric_or_none(value: Optional[str]) -> Optional[int]:
    if value is None or value.lower() in {"na", "none"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_base62_or_none(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.lower() in {"n", "na", "none", "unknown"}:
        return None
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    lookup = {char: index for index, char in enumerate(alphabet)}
    total = 0
    for char in normalized:
        if char not in lookup:
            return None
        total = total * 62 + lookup[char]
    return total


def parse_base62_list(value: Optional[str]) -> List[int]:
    if value is None or value.strip().lower() in {"n", "na", "none", "unknown"}:
        return []
    result: List[int] = []
    for part in value.strip().split(","):
        parsed = parse_base62_or_none(part)
        if parsed is not None:
            result.append(parsed)
    return result


def decode_base62_component(value: str) -> Optional[int]:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return {char: index for index, char in enumerate(alphabet)}.get(value)


def decode_compact_timestamp(value: str) -> str:
    if len(value) < 9:
        return value
    components = [decode_base62_component(char) for char in value[2:7]]
    if any(component is None for component in components):
        return value
    month, day, hour, minute, second = components
    millisecond = decode_base62_component(value[7])
    millisecond_low = decode_base62_component(value[8])
    if millisecond is None or millisecond_low is None:
        return value
    milliseconds = millisecond * 62 + millisecond_low
    return (
        f"20{value[:2]}-{month:02d}-{day:02d}T{hour:02d}:"
        f"{minute:02d}:{second:02d}.{milliseconds:03d}Z"
    )


def extract_click_timestamp(reason_code: str) -> tuple[str, str]:
    if len(reason_code) < 9:
        return reason_code, ""
    candidate = reason_code[-9:]
    decoded = decode_compact_timestamp(candidate)
    if decoded == candidate:
        return reason_code, ""
    return reason_code[:-9], decoded


def parse_readable_line(line: str) -> Optional[DecodedFlowSummary]:
    match = READABLE_RE.match(line.strip())
    if not match:
        return None
    summary = DecodedFlowSummary(
        source_type="readable", raw=line.strip(), timestamp=match.group("ts")
    )
    for part in (part.strip() for part in match.group("body").split(",")):
        separator = "=" if "=" in part else ":"
        if separator not in part:
            continue
        key, value = [item.strip() for item in part.split(separator, 1)]
        apply_field(summary, key, value)
    return summary


def parse_compact_line(line: str) -> Optional[DecodedFlowSummary]:
    stripped = line.strip()
    if stripped.startswith("H1|"):
        return parse_host_final_result_line(stripped)
    if stripped.startswith("S1|"):
        return parse_host_sample_line(stripped)
    if not stripped.startswith("L"):
        return None
    parts = stripped.split("|")
    if len(parts) < 3:
        return None
    protocol = parts[0][1:]
    if not protocol.isdigit():
        return None
    summary = DecodedFlowSummary(
        source_type="compact", raw=stripped, protocol_version=protocol
    )
    if len(parts) >= 4 and "=" not in parts[1] and "=" not in parts[2]:
        summary.sequence = parts[1]
        summary.event_code = parts[2]
        body_items = parts[3:]
        field_map = LEGACY_COMPACT_FIELD_MAP
    elif "=" not in parts[1]:
        summary.event_code = parts[1]
        body_items = parts[2:]
        field_map = LEGACY_COMPACT_FIELD_MAP
    else:
        body_items = parts[1:]
        field_map = MODERN_COMPACT_FIELD_MAP
    for item in body_items:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        apply_field(summary, field_map.get(key, key), value)
    return summary


def parse_host_final_result_line(line: str) -> DecodedFlowSummary:
    summary = DecodedFlowSummary(
        source_type="compact",
        raw=line,
        protocol_version="H1",
        event_code="FINAL_HOST_FLOW_RESULT",
    )
    for item in line.split("|")[1:]:
        if "=" in item:
            key, value = item.split("=", 1)
            apply_field(summary, HOST_FINAL_RESULT_FIELD_MAP.get(key, key), value)
    apply_host_final_result_defaults(summary)
    return summary


def apply_host_final_result_defaults(summary: DecodedFlowSummary) -> None:
    if summary.bxof is None and summary.config_id is not None:
        summary.bxof = str(summary.config_id)
    if summary.expected_click_count_clone is None:
        summary.expected_click_count_clone = 0
    if summary.interstitial_click_count is None:
        summary.interstitial_click_count = 0
        summary.interstitial_click = "no"
    if summary.interstitial_close_count is None:
        summary.interstitial_close_count = 0
    if summary.online_minutes is None:
        summary.online_minutes = 0
    if summary.matched_olt is None:
        summary.matched_olt = 0
    if summary.runtime_mode is None:
        summary.runtime_mode = RUNTIME_MODE_MAP["n"]
    if summary.home_page_did_finish is None:
        summary.home_page_did_finish = "no"
    if summary.home_page_js_ready is None:
        summary.home_page_js_ready = "no"
    if summary.home_page_load_timeout is None:
        summary.home_page_load_timeout = "no"
    if summary.home_page_load_failed is None:
        summary.home_page_load_failed = "no"
    if summary.home_page_web_content_process_terminated is None:
        summary.home_page_web_content_process_terminated = "no"
    if summary.home_page_did_commit is None:
        summary.home_page_did_commit = "no"
    if not summary.sample_kind:
        summary.sample_kind = derive_home_page_sample_kind(
            summary.home_page_did_finish, summary.home_page_js_ready
        )
    if summary.ads_probability_source is None and summary.ads_probability is None:
        summary.ads_probability_source = "none"
    if summary.total_time_source is None and summary.total_timeout_s is None:
        summary.total_time_source = "none"


def parse_host_sample_line(line: str) -> DecodedFlowSummary:
    summary = DecodedFlowSummary(
        source_type="compact",
        raw=line,
        protocol_version="S1",
        event_code="HOST_SAMPLE_RESULT",
    )
    for item in line.split("|")[1:]:
        if "=" in item:
            key, value = item.split("=", 1)
            apply_field(summary, HOST_FINAL_RESULT_FIELD_MAP.get(key, key), value)
    return summary


def apply_field(summary: DecodedFlowSummary, key: str, value: str) -> None:
    summary.extra_fields[key] = value
    if key == "timestamp":
        summary.timestamp = value
    elif key == "compact_timestamp":
        summary.timestamp = decode_compact_timestamp(value)
    elif key == "window":
        summary.window = value
    elif key == "config_id":
        summary.config_id = parse_base62_or_none(value)
    elif key == "url":
        summary.url = decode_compact_numeric_text(value)
    elif key == "ads":
        summary.ads = parse_numeric_or_none(value)
        if summary.ads is None:
            summary.ads = parse_base62_or_none(value)
    elif key == "bxof":
        summary.bxof = decode_compact_numeric_text(value)
    elif key == "expected_click_count":
        summary.expected_click_count = parse_base62_or_none(value)
    elif key == "expected_click_count_clone":
        summary.expected_click_count_clone = parse_base62_or_none(value)
    elif key == "interstitial_presentation_count":
        summary.interstitial_presentation_count = parse_base62_or_none(value)
    elif key == "interstitial_tracking":
        summary.interstitial_tracking = value
    elif key == "PmLH":
        summary.PmLH = parse_numeric_or_none(value)
        if summary.PmLH is None:
            summary.PmLH = parse_base62_or_none(value)
    elif key == "selected":
        summary.selected = decode_compact_selected(value)
    elif key == "selected_label":
        summary.selected_label = decode_compact_selected(value)
    elif key == "click":
        summary.click = CLICK_STATUS_MAP.get(value, value)
    elif key == "home_click_target":
        summary.home_click_target = decode_home_click_target(value)
    elif key == "page_jump":
        summary.page_jump = decode_yes_no(value)
    elif key == "interstitial_click":
        summary.interstitial_click = decode_yes_no(value)
    elif key == "interstitial_click_target":
        summary.interstitial_click_target = decode_interstitial_click_target(value)
    elif key == "interstitial_click_count":
        summary.interstitial_click_count = parse_base62_or_none(value)
        summary.interstitial_click = (
            "yes" if (summary.interstitial_click_count or 0) > 0 else "no"
        )
    elif key == "interstitial_close_count":
        summary.interstitial_close_count = parse_base62_or_none(value)
    elif key == "planned_click_attempts":
        summary.planned_click_attempts = decode_planned_click_attempts(value)
        if summary.planned_click_attempts and not summary.home_click_target:
            summary.home_click_target = str(summary.planned_click_attempts[0]["target_kind"])
        if summary.planned_click_attempts and not summary.click:
            summary.click = (
                "clicked"
                if any(item.get("did_click") is True for item in summary.planned_click_attempts)
                else "not_clicked"
            )
    elif key == "target_area":
        summary.target_area = TARGET_AREA_MAP.get(value, value)
    elif key == "monitor":
        summary.monitor = MONITOR_STATUS_MAP.get(value, value)
    elif key == "compact_status":
        apply_compact_status(summary, value)
    elif key == "final_reason":
        summary.final_reason = decode_final_reason(value)
    elif key == "duration_ms":
        summary.duration_ms = parse_numeric_or_none(value)
        if summary.duration_ms is None:
            summary.duration_ms = parse_base62_or_none(value)
    elif key == "runtime_mode":
        summary.runtime_mode = RUNTIME_MODE_MAP.get(value, value)
    elif key == "online_minutes":
        summary.online_minutes = parse_base62_or_none(value)
    elif key == "matched_olt":
        summary.matched_olt = parse_base62_or_none(value)
    elif key == "ads_probability":
        scaled = parse_base62_or_none(value)
        summary.ads_probability = None if scaled is None else scaled / 10000.0
    elif key == "ads_probability_source":
        summary.ads_probability_source = ADS_PROBABILITY_SOURCE_MAP.get(value, value)
    elif key == "Bkrf":
        milliseconds = parse_base62_or_none(value)
        summary.Bkrf = None if milliseconds is None else milliseconds / 1000.0
    elif key == "IDP":
        scaled = parse_base62_or_none(value)
        summary.IDP = None if scaled is None else scaled / 10000.0
    elif key == "IDP_hit":
        summary.IDP_hit = decode_yes_no(value)
    elif key == "qz":
        scaled = parse_base62_or_none(value)
        summary.qz = None if scaled is None else scaled / 10000.0
    elif key == "Hpdg":
        summary.Hpdg = parse_base62_or_none(value)
    elif key == "remain_hpdg":
        summary.remain_hpdg = parse_base62_or_none(value)
    elif key == "daily_bxof_open_count":
        summary.daily_bxof_open_count = parse_base62_or_none(value)
    elif key == "ltjTV_values":
        summary.ltjTV_values = parse_base62_list(value)
    elif key == "Jbgw_ms_values":
        summary.Jbgw_ms_values = parse_base62_list(value)
    elif key == "total_timeout_s":
        summary.total_timeout_s = parse_base62_or_none(value)
    elif key == "total_time_source":
        summary.total_time_source = TOTAL_TIME_SOURCE_MAP.get(value, value)
    elif key == "sample_kind":
        summary.sample_kind = SAMPLE_KIND_MAP.get(value, value)
    elif key == "home_page_flags":
        apply_home_page_flags(summary, value)
    elif key == "home_page_did_finish":
        summary.home_page_did_finish = decode_yes_no(value)
        if not summary.sample_kind:
            summary.sample_kind = derive_home_page_sample_kind(
                summary.home_page_did_finish, summary.home_page_js_ready
            )
    elif key == "home_page_js_ready":
        summary.home_page_js_ready = decode_yes_no(value)
        if not summary.sample_kind:
            summary.sample_kind = derive_home_page_sample_kind(
                summary.home_page_did_finish, summary.home_page_js_ready
            )
    elif key == "home_page_load_timeout":
        summary.home_page_load_timeout = decode_yes_no(value)
    elif key == "home_page_load_failed":
        summary.home_page_load_failed = decode_yes_no(value)
    elif key == "home_page_web_content_process_terminated":
        summary.home_page_web_content_process_terminated = decode_yes_no(value)
    elif key == "home_page_web_content_process_terminated_link":
        summary.home_page_web_content_process_terminated_link = decode_compact_numeric_text(value)
    elif key == "home_page_did_commit":
        summary.home_page_did_commit = decode_yes_no(value)
    elif key == "home_page_did_commit_link":
        summary.home_page_did_commit_link = decode_compact_numeric_text(value)
    elif key == "home_page_ready_reason":
        summary.home_page_ready_reason = HOME_PAGE_READY_REASON_MAP.get(value, value)
    elif key == "home_page_url":
        summary.home_page_url = value
        if not summary.url:
            summary.url = value
    elif key == "load_ms":
        summary.load_ms = parse_numeric_or_none(value)
    elif key == "inspect_target_ms":
        summary.inspect_target_ms = parse_numeric_or_none(value)
    elif key == "ocr_click_ms":
        summary.ocr_click_ms = parse_numeric_or_none(value)
    elif key == "tail_ms":
        summary.tail_ms = parse_numeric_or_none(value)
    elif key == "interaction_failure_detail":
        summary.interaction_failure_detail = value


def apply_home_page_flags(summary: DecodedFlowSummary, value: str) -> None:
    flags = {
        "0": ("no", "no"),
        "1": ("yes", "no"),
        "2": ("no", "yes"),
        "3": ("yes", "yes"),
    }.get(value.strip())
    if flags is None:
        return
    summary.home_page_did_finish, summary.home_page_js_ready = flags
    if not summary.sample_kind:
        summary.sample_kind = derive_home_page_sample_kind(*flags)


def derive_home_page_sample_kind(
    did_finish: Optional[str], js_ready: Optional[str]
) -> Optional[str]:
    if did_finish == "yes" and js_ready == "yes":
        return SAMPLE_KIND_MAP["hfhr"]
    if did_finish == "yes":
        return SAMPLE_KIND_MAP["hf"]
    if js_ready == "yes":
        return SAMPLE_KIND_MAP["hr"]
    return None


def decode_yes_no(value: str) -> str:
    if value in {"1", "yes", "true"}:
        return "yes"
    if value in {"0", "no", "false"}:
        return "no"
    return value


def decode_final_reason(value: str) -> str:
    if value.startswith("e") and len(value) > 1:
        return INTERACTION_FAILURE_REASON_MAP.get(
            value[1:], f"interaction-execution-failed:unknown-{value[1:]}"
        )
    return FINAL_REASON_MAP.get(value, value)


def decode_home_click_target(value: str) -> str:
    return {
        "b": "banner",
        "a": "anchored",
        "w": "web_element",
        "n": "none",
        "u": "unknown",
    }.get(value, value)


def decode_interstitial_click_target(value: str) -> str:
    return {
        "c": "close_related",
        "o": "other_region",
        "n": "none",
        "u": "unknown",
    }.get(value, value)


def decode_compact_numeric_text(value: str) -> str:
    if re.fullmatch(r"u\d+", value) or value.isdigit():
        return value
    decoded = parse_base62_or_none(value)
    return str(decoded) if decoded is not None else value


def decode_compact_selected(value: str) -> str:
    if value.lower() == "n":
        return "none"
    if re.fullmatch(r"[wba]+", value):
        label_map = {"w": "web_element", "b": "banner", "a": "anchored"}
        return ",".join(label_map.get(character, character) for character in value)
    mapped = SELECTED_LABEL_MAP.get(value)
    if mapped:
        return mapped
    if value.isdigit():
        return value
    decoded = parse_base62_or_none(value)
    return str(decoded) if decoded is not None else value


def decode_planned_click_attempts(value: str) -> List[Dict[str, object]]:
    if value.lower() == "n":
        return []
    attempts: List[Dict[str, object]] = []
    for item in value.split(","):
        compact_item = item
        click_implementation = ""
        target_path = ""
        error_detail = ""
        if "~" in item:
            parts = item.split("~")
            if len(parts) >= 3:
                compact_item = parts[0]
                click_implementation = decode_compact_text_field(parts[1])
                target_path = decode_compact_text_field(parts[2])
            elif len(parts) == 2:
                compact_item = parts[0]
                error_detail = decode_compact_text_field(parts[1])
        if len(compact_item) >= 3:
            navigation_code = parse_base62_or_none(compact_item[2])
            rest = compact_item[3:] if len(compact_item) > 3 else ""
            page_context = ""
            completion_status = ""
            popup_redirect_source = ""
            reason_code = rest
            if rest and rest[0] in PAGE_CONTEXT_MAP:
                page_context = PAGE_CONTEXT_MAP[rest[0]]
                reason_code = rest[1:]
            if reason_code and reason_code[0] in ATTEMPT_COMPLETION_STATUS_MAP:
                completion_status = ATTEMPT_COMPLETION_STATUS_MAP[reason_code[0]]
                reason_code = reason_code[1:]
            target_kind = PLANNED_TARGET_KIND_MAP.get(
                compact_item[0], decode_compact_text_field(compact_item[0])
            )
            if target_kind in {"banner", "anchored"} and reason_code:
                popup_redirect_source, reason_code = consume_popup_redirect_token(reason_code)
            reason_code, click_timestamp = extract_click_timestamp(reason_code)
            attempts.append(
                {
                    "index": len(attempts) + 1,
                    "target_kind": target_kind,
                    "did_click": {"1": True, "0": False, "n": None}.get(
                        compact_item[1], None
                    ),
                    "reason": COMPACT_CLICK_REASON_MAP.get(reason_code, "")
                    if reason_code
                    else "",
                    "click_timestamp": click_timestamp,
                    "navigation_code": navigation_code,
                    "navigation_result": CLICK_NAVIGATION_CODE_MAP.get(
                        navigation_code, ""
                    ),
                    "click_implementation": ""
                    if click_implementation in {"", "n"}
                    else click_implementation,
                    "target_path": "" if target_path in {"", "n"} else target_path,
                    "error_detail": "" if error_detail in {"", "n"} else error_detail,
                    "page_context": page_context,
                    "page_context_result": readable_page_context(page_context),
                    "completion_status": completion_status,
                    "popup_redirect_source": popup_redirect_source,
                    "popup_redirect_result": readable_popup_redirect_source(
                        popup_redirect_source
                    ),
                }
            )
            continue
        parts = item.split("~")
        if len(parts) == 3:
            navigation_code = parse_base62_or_none(parts[2])
            attempts.append(
                {
                    "index": len(attempts) + 1,
                    "target_kind": PLANNED_TARGET_KIND_MAP.get(
                        parts[0], decode_compact_text_field(parts[0])
                    ),
                    "did_click": {"1": True, "0": False, "n": None}.get(
                        parts[1], None
                    ),
                    "reason": "",
                    "navigation_code": navigation_code,
                    "navigation_result": CLICK_NAVIGATION_CODE_MAP.get(
                        navigation_code, ""
                    ),
                    "page_context": "",
                    "page_context_result": "",
                    "popup_redirect_source": "",
                    "popup_redirect_result": "",
                }
            )
            continue
        if len(parts) < 4:
            continue
        raw_navigation_code = (
            parse_base62_or_none(parts[4]) if len(parts) >= 5 else None
        )
        navigation_code = normalize_legacy_navigation_code(raw_navigation_code)
        page_token = parts[5] if len(parts) >= 6 else ""
        page_context = PAGE_CONTEXT_MAP.get(
            page_token, page_token if page_token in {"home", "secondary"} else ""
        )
        popup_token = parts[6] if len(parts) >= 7 else ""
        if popup_token in {"none", "createWebViewWith", "decidePolicy"} or "+" in popup_token:
            popup_redirect_source = popup_token
        else:
            popup_redirect_source = POPUP_REDIRECT_SOURCE_MAP.get(popup_token, "")
        attempts.append(
            {
                "index": parse_base62_or_none(parts[0]) or 0,
                "target_kind": PLANNED_TARGET_KIND_MAP.get(
                    parts[1], decode_compact_text_field(parts[1])
                ),
                "did_click": {"1": True, "0": False, "n": None}.get(
                    parts[2], None
                ),
                "reason": COMPACT_CLICK_REASON_MAP.get(parts[3], "other"),
                "navigation_code": navigation_code,
                "navigation_result": CLICK_NAVIGATION_CODE_MAP.get(
                    navigation_code, ""
                ),
                "page_context": page_context,
                "page_context_result": readable_page_context(page_context),
                "popup_redirect_source": popup_redirect_source,
                "popup_redirect_result": readable_popup_redirect_source(
                    popup_redirect_source
                ),
            }
        )
    return attempts


def consume_popup_redirect_token(token: str) -> tuple[str, str]:
    if len(token) >= 2 and token[:2] in POPUP_REDIRECT_SOURCE_MAP:
        return POPUP_REDIRECT_SOURCE_MAP[token[:2]], token[2:]
    if token and token[0] in POPUP_REDIRECT_SOURCE_MAP:
        return POPUP_REDIRECT_SOURCE_MAP[token[0]], token[1:]
    return "", token


def readable_popup_redirect_source(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "+" in text:
        parts = [readable_popup_redirect_source(part) for part in text.split("+")]
        return " + ".join(part for part in parts if part)
    return {
        "none": "未走到新窗口改当前页",
        "createWebViewWith": "走到 createWebViewWith 改当前页",
        "decidePolicy": "走到 decidePolicy 改当前页",
        "createWebViewWith+decidePolicy": (
            "走到 createWebViewWith 改当前页 + 走到 decidePolicy 改当前页"
        ),
        "decidePolicy+createWebViewWith": (
            "走到 decidePolicy 改当前页 + 走到 createWebViewWith 改当前页"
        ),
    }.get(text, text)


def readable_page_context(value: object) -> str:
    text = str(value or "").strip()
    return PAGE_CONTEXT_DISPLAY_MAP.get(text, text) if text else ""


def normalize_legacy_navigation_code(value: Optional[int]) -> Optional[int]:
    if value in {1, 3, 5, 7, 9}:
        return 1
    if value in {0, 2, 4, 6, 8}:
        return 0
    return value


def decode_compact_text_field(value: str) -> str:
    result: List[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            next_character = value[index + 1]
            result.append({"t": "~", "c": ",", "p": "|", "\\": "\\"}.get(next_character, next_character))
            index += 2
            continue
        result.append(character)
        index += 1
    return "".join(result)


def apply_compact_status(summary: DecodedFlowSummary, value: str) -> None:
    if len(value) < 4:
        return
    summary.click = CLICK_STATUS_MAP.get(value[0], value[0])
    summary.extra_fields["derived_try"] = value[1]
    summary.extra_fields["derived_click"] = value[2]
    summary.monitor = MONITOR_STATUS_MAP.get(value[3], value[3])


def decode_text(text: str) -> List[DecodedFlowSummary]:
    summaries: List[DecodedFlowSummary] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        decoded = parse_readable_line(line) or parse_compact_line(line)
        if decoded:
            summaries.append(decoded)
    return summaries


def decode_extra(extra: str) -> list[dict[str, object]]:
    """Decode one log payload without performing any external I/O."""
    if not isinstance(extra, str):
        raise TypeError("extra 必须是字符串")
    if len(extra) > MAX_EXTRA_LENGTH:
        raise ValueError("extra 超过解析长度限制")
    h1_records = extract_h1_records(extra)
    decoded = [parse_host_final_result_line(record) for record in h1_records]
    decoded.extend(decode_text(remove_h1_records(extra)))
    if len(decoded) > MAX_RECORDS_PER_EXTRA:
        raise ValueError("extra 中记录数超过限制")
    return [asdict(item) for item in decoded]
