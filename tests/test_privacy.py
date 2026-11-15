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
