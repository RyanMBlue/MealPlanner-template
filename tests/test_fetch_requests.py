"""Tests for fetch_requests pure-function helpers."""
from datetime import date as _date, datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from fetch_requests import (
    SECTION_KEYS,
    extract_sender,
    extract_text_body,
    is_allowed,
    normalize_reply_body,
    parse_sections,
    process_message,
    render_output,
    run_target_monday,
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


class TestRunTargetMonday:
    """Request ingestion must target the same week as the rest of the workflow
    (issue #3): honor $TARGET_MONDAY when set, else the upcoming Monday."""

    def test_honors_explicit_target_monday_env(self, monkeypatch):
        monkeypatch.setenv("TARGET_MONDAY", "2026-08-03")
        # Run "on" a Friday well before the explicit target — env must win.
        now = datetime(2026, 7, 10, 9, 0, tzinfo=ZoneInfo("America/New_York"))
        assert run_target_monday("America/New_York", now) == _date(2026, 8, 3)

    def test_falls_back_to_upcoming_when_unset(self, monkeypatch):
        monkeypatch.delenv("TARGET_MONDAY", raising=False)
        now = datetime(2026, 7, 3, 9, 0, tzinfo=ZoneInfo("America/New_York"))  # Friday
        assert run_target_monday("America/New_York", now) == _date(2026, 7, 6)

    def test_blank_env_falls_back_to_upcoming(self, monkeypatch):
        monkeypatch.setenv("TARGET_MONDAY", "   ")
        now = datetime(2026, 7, 3, 9, 0, tzinfo=ZoneInfo("America/New_York"))  # Friday
        assert run_target_monday("America/New_York", now) == _date(2026, 7, 6)


class TestSubjectTag:
    def test_format(self):
        from datetime import date
        assert subject_tag(date(2026, 5, 18)) == "[meal-plan request: 2026-05-18]"


class TestNormalizeReplyBody:
    def test_drops_gmail_on_wrote_attribution_line(self):
        body = (
            "## Must have / Must avoid\n"
            "- no fish\n"
            "\n"
            "On Fri, May 15, 2026 at 8:00 AM Meal Plan <meals@example.com> wrote:\n"
            "> quoted stuff\n"
        )
        result = normalize_reply_body(body)
        assert "no fish" in result
        assert "wrote:" not in result

    def test_drops_outlook_original_message_line(self):
        body = (
            "## Soft preferences\n"
            "- lean Italian\n"
            "-----Original Message-----\n"
            "> From: meals@example.com\n"
        )
        result = normalize_reply_body(body)
        assert "lean Italian" in result
        assert "Original Message" not in result

    def test_strips_leading_quote_prefixes(self):
        # The core fix: answers typed inside the quoted block keep their
        # headings, so dequoting lets parse_sections see them.
        body = "> ## Use up\n> Ground beef, fresh green beans\n"
        result = normalize_reply_body(body)
        assert result == "## Use up\nGround beef, fresh green beans"

    def test_strips_nested_quote_prefixes(self):
        body = ">> ## Use up\n>> arborio rice\n"
        result = normalize_reply_body(body)
        assert result == "## Use up\narborio rice"

    def test_unquoted_body_passes_through(self):
        body = "## Use up\n- arborio rice"
        assert normalize_reply_body(body) == body


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

    def test_parenthetical_hint_lines_are_dropped(self):
        # The prompt's placeholder hints sit under each heading; they must not
        # leak into captured content when a reply quotes the whole template.
        body = (
            "## Must have / Must avoid\n"
            '(hard constraints — e.g. "no fish", "tacos one night")\n'
            "no dairy\n"
        )
        result = parse_sections(body)
        assert result["must"].strip() == "no dairy"
        assert "hard constraints" not in result["must"]

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

    def test_real_reply_typed_inside_quoted_template(self):
        # Regression for issue #43: a reply that quotes the whole prompt and
        # types answers *inside* the quote (directly under the quoted headings,
        # which is what the prompt instructs) must still be captured. Body
        # modeled on the real 2026-07-06 reply that was silently dropped.
        body = (
            "On Jul 3, 2026 at 10:11 AM -0400, Meal Plan <meals@example.com>, wrote:\n"
            "\n"
            "> What do you want for the week of Mon Jul 06 — Sun Jul 12?\n"
            ">\n"
            "> Reply to this email. Type under each heading below.\n"
            "> Leave a section blank if there's nothing for it.\n"
            "> Send any time before Saturday 8am ET.\n"
            ">\n"
            "> ## Must have / Must avoid\n"
            '> (hard constraints — e.g. "no fish", "tacos one night")\n'
            ">\n"
            ">\n"
            "> ## Soft preferences\n"
            "> (suggestions — ...)\n"
            "> The kids won't be home for dinner Tuesday through Friday next week.\n"
            ">\n"
            "> ## Use up\n"
            "> (ingredients in the fridge/pantry to lean on)\n"
            "> Ground beef, fresh green beans\n"
        )
        msg = _make_msg("gina@example.com", body)
        result = process_message(msg, ["gina@example.com"])
        assert result is not None
        assert result["sections"]["must"].strip() == ""
        assert "kids won't be home" in result["sections"]["soft"]
        assert result["sections"]["use_up"].strip() == "Ground beef, fresh green beans"
        # Template scaffolding must not leak into captured content.
        assert "suggestions" not in result["sections"]["soft"]
        assert "ingredients in the fridge" not in result["sections"]["use_up"]
        assert "What do you want" not in result["sections"]["soft"]


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
