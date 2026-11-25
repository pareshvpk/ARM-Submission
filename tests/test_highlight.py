from __future__ import annotations

from sentinel.highlight import ANSI_BOLD_RED, ANSI_RESET, format_highlighted


def test_no_spans_returns_text_unchanged():
    text = "Your SBI account is blocked today"
    assert format_highlighted(text, [], use_color=False) == text
    assert format_highlighted(text, None, use_color=False) == text
    assert format_highlighted(text, [], use_color=True) == text


def test_one_span_plain_includes_type():
    text = "Your SBI account is blocked today"
    start = text.index("blocked")
    cue_spans = [{"start": start, "end": start + len("blocked"), "type": "threat"}]
    result = format_highlighted(text, cue_spans, use_color=False)
    assert result == "Your SBI account is [[blocked]](threat) today"


def test_one_span_colour_is_bold_red():
    text = "account blocked"
    cue_spans = [{"start": 8, "end": 15, "type": "threat"}]
    result = format_highlighted(text, cue_spans, use_color=True)
    assert result == f"account {ANSI_BOLD_RED}blocked{ANSI_RESET}"
    assert ANSI_BOLD_RED in result
    assert ANSI_RESET in result


def test_overlapping_spans_are_merged():
    text = "0123456789"
    # Two spans overlap on "345"; the union "01234567" is marked once.
    cue_spans = [
        {"start": 0, "end": 5, "type": "urgency"},
        {"start": 3, "end": 8, "type": "threat"},
    ]
    result = format_highlighted(text, cue_spans, use_color=False)
    assert result == "[[01234567]](urgency)89"
    assert result.count("[[") == 1

    coloured = format_highlighted(text, cue_spans, use_color=True)
    assert coloured == f"{ANSI_BOLD_RED}01234567{ANSI_RESET}89"
    assert coloured.count(ANSI_BOLD_RED) == 1


def test_span_at_start_and_end():
    text = "blocked KYC"
    cue_spans = [
        {"start": 0, "end": 7, "type": "threat"},
        {"start": 8, "end": 11, "type": "credential_request"},
    ]
    result = format_highlighted(text, cue_spans, use_color=False)
    assert result == "[[blocked]](threat) [[KYC]](credential_request)"


def test_hinglish_text():
    text = "Aapka bijli connection aaj raat kat jayega"
    start = text.index("bijli")
    cue_spans = [{"start": start, "end": start + len("bijli"), "type": "impersonation"}]
    result = format_highlighted(text, cue_spans, use_color=False)
    assert result == "Aapka [[bijli]](impersonation) connection aaj raat kat jayega"

    coloured = format_highlighted(text, cue_spans, use_color=True)
    assert f"{ANSI_BOLD_RED}bijli{ANSI_RESET}" in coloured


def test_out_of_range_span_is_ignored_not_crash():
    text = "hello world"
    cue_spans = [
        {"start": -1, "end": 3, "type": "threat"},
        {"start": 0, "end": 999, "type": "threat"},
        {"start": 50, "end": 60, "type": "threat"},
        {"start": 5, "end": 5, "type": "threat"},
        {"start": "0", "end": "5", "type": "threat"},
    ]
    assert format_highlighted(text, cue_spans, use_color=False) == text
    assert format_highlighted(text, cue_spans, use_color=True) == text


def test_valid_span_survives_alongside_invalid_span():
    text = "hello blocked"
    cue_spans = [
        {"start": 0, "end": 999, "type": "urgency"},
        {"start": 6, "end": 13, "type": "threat"},
    ]
    result = format_highlighted(text, cue_spans, use_color=False)
    assert result == "hello [[blocked]](threat)"
