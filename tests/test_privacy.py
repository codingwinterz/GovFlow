from app.privacy import mask_identifiers


def test_masks_spaced_twelve_digit_identifier():
    assert mask_identifiers("ID 9876 5432 1098 on file") == "ID XXXX XXXX 1098 on file"


def test_masks_contiguous_and_dashed_forms():
    assert mask_identifiers("987654321098") == "XXXX XXXX 1098"
    assert mask_identifiers("9876-5432-1098") == "XXXX XXXX 1098"


def test_leaves_other_numbers_alone():
    assert mask_identifiers("survey 123/4, area 2500, 2026-11-15") == "survey 123/4, area 2500, 2026-11-15"
    assert mask_identifiers("12345678901234") == "12345678901234"   # 14 digits: not an Aadhaar-like id


def test_masks_inside_nested_payloads():
    payload = {"fields": [{"name": "id_number", "value": "9876 5432 1098"}], "n": 5}
    assert mask_identifiers(payload) == {"fields": [{"name": "id_number", "value": "XXXX XXXX 1098"}], "n": 5}


def test_redacts_api_key_shapes():
    from app.privacy import redact_secrets
    text = "a AIza" + "B" * 35 + " b AQ" + ".fake_value_" + "0" * 24 + " c sk-ant-" + "x" * 24
    assert redact_secrets(text) == "a [redacted] b [redacted] c [redacted]"


def test_redacts_the_configured_key_whatever_its_shape(monkeypatch):
    from app.privacy import redact_secrets
    monkeypatch.setenv("GEMINI_API_KEY", "odd-shaped-key-123")
    assert redact_secrets({"error": ["failed for odd-shaped-key-123"]}) == {"error": ["failed for [redacted]"]}


def test_audit_payload_is_redacted(monkeypatch):
    from app.audit import log_action
    from app.models import AuditLog, make_engine, make_session
    monkeypatch.setenv("GEMINI_API_KEY", "odd-shaped-key-123")
    with make_session(make_engine("sqlite://")) as s:
        log_action(s, None, "system", "x", {"error": "odd-shaped-key-123 / 9876 5432 1098"})
        assert s.query(AuditLog).one().payload_json == '{"error": "[redacted] / XXXX XXXX 1098"}'
