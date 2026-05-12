"""Tests for fetch_requests pure-function helpers."""
from datetime import date as _date, datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from fetch_requests import (
    SECTION_KEYS,
    extract_sender,
    extract_text_body,
    is_allowed,
    parse_sections,
    process_message,
    render_output,
    strip_quoted_reply,
    subject_tag,
    target_monday,
)


class TestTargetMonday:
    def test_friday_returns_following_monday(self):
        # Fri 2026-05-15 → Mon 2026-05-18
        now = datetime(2026, 5, 15, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert target_monday(now).isoformat() == "2026-05-18"

    def test_saturday_returns_two_days_later(self):
        # Sat 2026-05-16 → Mon 2026-05-18
        now = datetime(2026, 5, 16, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert target_monday(now).isoformat() == "2026-05-18"

    def test_monday_returns_next_monday_not_today(self):
        # Mon 2026-05-18 at 9am → Mon 2026-05-25 (we look ahead to the *next*
        # plan week so a Friday rerun never matches the current week).
        now = datetime(2026, 5, 18, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert target_monday(now).isoformat() == "2026-05-25"


class TestSubjectTag:
    def test_format(self):
        from datetime import date
        assert subject_tag(date(2026, 5, 18)) == "[meal-plan request: 2026-05-18]"


class TestStripQuotedReply:
    def test_cuts_at_gmail_on_wrote_marker(self):
        body = (
            "## Must have / Must avoid\n"
            "- no fish\n"
            "\n"
            "On Fri, May 15, 2026 at 8:00 AM Meal Plan <meals@example.com> wrote:\n"
            "> What do you want for the week of...\n"
        )
        result = strip_quoted_reply(body)
        assert "no fish" in result
        assert "wrote:" not in result
        assert "What do you want" not in result

    def test_cuts_at_outlook_original_message_marker(self):
        body = (
            "## Soft preferences\n"
            "- lean Italian\n"
            "\n"
            "-----Original Message-----\n"
            "From: meals@example.com\n"
            "Subject: ...\n"
        )
        result = strip_quoted_reply(body)
        assert "lean Italian" in result
        assert "Original Message" not in result

    def test_no_marker_returns_input_unchanged(self):
        body = "## Use up\n- arborio rice\n"
        assert strip_quoted_reply(body) == body

    def test_strips_trailing_whitespace_only_lines(self):
        # "On Fri wrote:" matches the marker; the kept portion has trailing
        # blank/whitespace-only lines that should be trimmed.
        body = "## Soft preferences\n- lean Italian\n   \n\nOn Fri wrote:\n> q\n"
        result = strip_quoted_reply(body)
        assert "lean Italian" in result
        assert "wrote:" not in result
        # Kept portion shouldn't end with the stray whitespace-only lines.
        assert not result.endswith("   \n")

    def test_cuts_at_bare_blockquote_when_no_preamble_marker(self):
        # A client that omits the "On ... wrote:" preamble can leave just the
        # `> ` quoted block. Cut at the first `>` line preceded by a blank.
        body = (
            "## Must have / Must avoid\n"
            "- no fish\n"
            "\n"
            "> ## Must have / Must avoid\n"
            "> (hard constraints...)\n"
        )
        result = strip_quoted_reply(body)
        assert "no fish" in result
        assert "hard constraints" not in result

    def test_blockquote_without_preceding_blank_is_preserved(self):
        # A `>` line without a preceding blank is user content (e.g. a typo or
        # markdown blockquote), not a quote-reply marker.
        body = "## Use up\n- arborio rice\n> a note from me\n"
        assert strip_quoted_reply(body) == body


class TestParseSections:
    def test_all_three_sections_present(self):
        body = (
            "## Must have / Must avoid\n"
            "- no fish\n"
            "- tacos one night\n"
            "\n"
            "## Soft preferences\n"
            "- lean Italian\n"
            "\n"
            "## Use up\n"
            "- arborio rice\n"
        )
        result = parse_sections(body)
        assert result["must"].strip() == "- no fish\n- tacos one night"
        assert result["soft"].strip() == "- lean Italian"
        assert result["use_up"].strip() == "- arborio rice"

    def test_missing_section_yields_empty_string(self):
        body = "## Must have / Must avoid\n- no fish\n"
        result = parse_sections(body)
        assert result["must"].strip() == "- no fish"
        assert result["soft"] == ""
        assert result["use_up"] == ""

    def test_content_before_first_heading_dropped(self):
        body = (
            "Hi there!\n"
            "Some preamble.\n"
            "\n"
            "## Must have / Must avoid\n"
            "- no fish\n"
        )
        result = parse_sections(body)
        assert "Hi there" not in result["must"]
        assert result["must"].strip() == "- no fish"

    def test_unknown_section_dropped(self):
        body = (
            "## Random heading\n"
            "- something\n"
            "\n"
            "## Must have / Must avoid\n"
            "- no fish\n"
        )
        result = parse_sections(body)
        assert "something" not in result["must"]
        assert "something" not in result["soft"]
        assert "something" not in result["use_up"]

    def test_case_insensitive_heading_match(self):
        body = "## MUST HAVE / MUST AVOID\n- no fish\n"
        result = parse_sections(body)
        assert result["must"].strip() == "- no fish"

    def test_h3_heading_also_matches(self):
        body = "### Must have / Must avoid\n- no fish\n"
        result = parse_sections(body)
        assert result["must"].strip() == "- no fish"

    def test_all_empty_returns_empty_strings(self):
        body = (
            "## Must have / Must avoid\n"
            "\n"
            "## Soft preferences\n"
            "\n"
            "## Use up\n"
        )
        result = parse_sections(body)
        assert result["must"] == ""
        assert result["soft"] == ""
        assert result["use_up"] == ""

    def test_section_keys_constant(self):
        assert SECTION_KEYS == ("must", "soft", "use_up")


class TestExtractSender:
    def test_address_only(self):
        msg = EmailMessage()
        msg["From"] = "user@example.com"
        assert extract_sender(msg) == "user@example.com"

    def test_name_and_address(self):
        msg = EmailMessage()
        msg["From"] = "Jane Doe <user@example.com>"
        assert extract_sender(msg) == "user@example.com"

    def test_case_normalized(self):
        msg = EmailMessage()
        msg["From"] = "Ryan <RYAN@Example.COM>"
        assert extract_sender(msg) == "ryan@example.com"

    def test_missing_returns_none(self):
        msg = EmailMessage()
        assert extract_sender(msg) is None


class TestIsAllowed:
    def test_present_in_allowlist(self):
        assert is_allowed("ryan@example.com", ["ryan@example.com", "gina@example.com"])

    def test_case_insensitive(self):
        assert is_allowed("RYAN@example.com", ["ryan@example.com"])

    def test_absent_from_allowlist(self):
        assert not is_allowed("evil@example.com", ["ryan@example.com"])

    def test_none_sender_rejected(self):
        assert not is_allowed(None, ["ryan@example.com"])


class TestExtractTextBody:
    def test_plain_text_message(self):
        msg = EmailMessage()
        msg.set_content("hello world\n")
        assert extract_text_body(msg).strip() == "hello world"

    def test_multipart_prefers_plain(self):
        msg = EmailMessage()
        msg.set_content("plain version\n")
        msg.add_alternative("<p>html version</p>", subtype="html")
        body = extract_text_body(msg)
        assert "plain version" in body
        assert "html version" not in body

    def test_html_only_falls_back_to_html_stripped(self):
        # If no text/plain part exists, we accept the html part as-is.
        # The parser tolerates extra markup because heading detection is
        # robust enough; we don't ship an HTML→text converter for this.
        msg = EmailMessage()
        msg.set_content("<p>fallback</p>", subtype="html")
        body = extract_text_body(msg)
        assert "fallback" in body


def _make_msg(from_addr: str, body: str, sent: str = "Fri, 15 May 2026 19:42:00 -0400") -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["Date"] = sent
    msg["Subject"] = "Re: [meal-plan request: 2026-05-18]"
    msg.set_content(body)
    return msg


class TestProcessMessage:
    def test_well_formed_reply_returns_contribution(self):
        body = (
            "## Must have / Must avoid\n- no fish\n\n"
            "## Soft preferences\n- lean Italian\n\n"
            "## Use up\n- arborio rice\n"
        )
        msg = _make_msg("ryan@example.com", body)
        result = process_message(msg, ["ryan@example.com"])
        assert result is not None
        assert result["sender"] == "ryan@example.com"
        assert "2026-05-15" in result["timestamp"]
        assert result["sections"]["must"].strip() == "- no fish"
        assert result["sections"]["soft"].strip() == "- lean Italian"
        assert result["sections"]["use_up"].strip() == "- arborio rice"

    def test_rejects_disallowed_sender(self):
        msg = _make_msg("evil@example.com", "## Must have / Must avoid\n- pwned\n")
        assert process_message(msg, ["ryan@example.com"]) is None

    def test_strips_gmail_quoted_reply_before_parsing(self):
        body = (
            "## Must have / Must avoid\n- no fish\n\n"
            "On Fri, May 15, 2026 at 8:00 AM Meal Plan wrote:\n"
            "> ## Must have / Must avoid\n"
            "> (hard constraints...)\n"
        )
        msg = _make_msg("ryan@example.com", body)
        result = process_message(msg, ["ryan@example.com"])
        assert result is not None
        assert result["sections"]["must"].strip() == "- no fish"

    def test_all_empty_sections_returns_none(self):
        body = (
            "## Must have / Must avoid\n\n"
            "## Soft preferences\n\n"
            "## Use up\n"
        )
        msg = _make_msg("ryan@example.com", body)
        assert process_message(msg, ["ryan@example.com"]) is None


class TestRenderOutput:
    def test_single_contribution(self):
        contributions = [{
            "sender": "ryan@example.com",
            "timestamp": "2026-05-15T19:42",
            "sections": {"must": "- no fish", "soft": "- lean Italian", "use_up": "- arborio rice"},
        }]
        output = render_output(_date(2026, 5, 18), contributions)
        assert output is not None
        assert "# Captured requests for the week of 2026-05-18" in output
        assert "## Must have / Must avoid" in output
        assert "<!-- from: ryan@example.com at 2026-05-15T19:42 -->" in output
        assert "- no fish" in output
        assert "- lean Italian" in output
        assert "- arborio rice" in output

    def test_multiple_contributions_merged_per_section(self):
        contributions = [
            {
                "sender": "ryan@example.com",
                "timestamp": "2026-05-15T19:42",
                "sections": {"must": "- no fish", "soft": "", "use_up": ""},
            },
            {
                "sender": "gina@example.com",
                "timestamp": "2026-05-15T20:10",
                "sections": {"must": "- tacos one night", "soft": "- lighter meals", "use_up": ""},
            },
        ]
        output = render_output(_date(2026, 5, 18), contributions)
        assert output is not None
        assert output.index("- no fish") < output.index("- tacos one night")
        assert "<!-- from: ryan@example.com" in output
        assert "<!-- from: gina@example.com" in output
        assert "- lighter meals" in output

    def test_empty_section_omits_traceability_comment(self):
        contributions = [{
            "sender": "ryan@example.com",
            "timestamp": "2026-05-15T19:42",
            "sections": {"must": "- no fish", "soft": "", "use_up": ""},
        }]
        output = render_output(_date(2026, 5, 18), contributions)
        # The empty Soft preferences section should not carry a traceability
        # comment from a contributor who didn't fill it in.
        soft_idx = output.index("## Soft preferences")
        next_h2 = output.index("## Use up", soft_idx)
        soft_block = output[soft_idx:next_h2]
        assert "<!-- from:" not in soft_block

    def test_all_sections_empty_returns_none(self):
        contributions = [{
            "sender": "ryan@example.com",
            "timestamp": "2026-05-15T19:42",
            "sections": {"must": "", "soft": "", "use_up": ""},
        }]
        assert render_output(_date(2026, 5, 18), contributions) is None

    def test_no_contributions_returns_none(self):
        assert render_output(_date(2026, 5, 18), []) is None
