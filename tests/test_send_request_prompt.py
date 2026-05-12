"""Tests for send_request_prompt body composition + Resend payload shape."""
from datetime import date

from send_request_prompt import build_message, build_payload


class TestBuildMessage:
    def test_subject_includes_target_monday_tag(self):
        subject, _ = build_message(date(2026, 5, 18))
        assert subject == "[meal-plan request: 2026-05-18]"

    def test_body_has_three_headings_and_date_range(self):
        _, body = build_message(date(2026, 5, 18))
        assert "## Must have / Must avoid" in body
        assert "## Soft preferences" in body
        assert "## Use up" in body
        # Date range: Mon May 18 — Sun May 24
        assert "May 18" in body
        assert "May 24" in body

    def test_body_instructs_reply(self):
        _, body = build_message(date(2026, 5, 18))
        assert "Reply" in body or "reply" in body


class TestBuildPayload:
    def _config(self) -> dict:
        return {
            "email_from": "Meal Plan <meals@example.com>",
            "email_recipients": ["ryan@example.com", "gina@example.com"],
            "requests": {"gmail_user": "ryan@example.com"},
        }

    def test_includes_reply_to_gmail_user(self):
        payload = build_payload(self._config(), "subject", "body")
        assert payload["reply_to"] == ["ryan@example.com"]

    def test_basic_fields_match_config(self):
        payload = build_payload(self._config(), "subject", "body")
        assert payload["from"] == "Meal Plan <meals@example.com>"
        assert payload["to"] == ["ryan@example.com", "gina@example.com"]
        assert payload["subject"] == "subject"
        assert payload["text"] == "body"

    def test_omits_reply_to_when_requests_block_missing(self):
        config = self._config()
        del config["requests"]
        payload = build_payload(config, "subject", "body")
        assert "reply_to" not in payload

    def test_omits_reply_to_when_gmail_user_missing(self):
        config = self._config()
        config["requests"] = {}
        payload = build_payload(config, "subject", "body")
        assert "reply_to" not in payload
