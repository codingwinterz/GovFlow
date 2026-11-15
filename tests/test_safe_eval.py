import pytest

from app.safe_eval import UnknownName, UnsafeExpression, check_expression, evaluate, names_in


def test_arithmetic_uses_names():
    assert evaluate("area_sqm * rate * multiplier", {"area_sqm": 100, "rate": 50, "multiplier": 2}) == 10000


def test_parentheses_and_precedence():
    assert evaluate("(a + b) * c", {"a": 1, "b": 2, "c": 3}) == 9


def test_boolean_logic_and_comparison():
    names = {"x": 5, "ok": True}
    assert evaluate("ok and x >= 5", names) is True
    assert evaluate("not ok or x < 0", names) is False


def test_dotted_access_reads_nested_dicts():
    names = {"ownership_record": {"present": True, "owner_name": "Asha Naik"}}
    assert evaluate("ownership_record.present", names) is True
    assert evaluate("ownership_record.owner_name == 'Asha Naik'", names) is True


def test_unknown_name_raises():
    with pytest.raises(UnknownName):
        evaluate("missing_field > 1", {})


def test_unknown_nested_key_raises():
    with pytest.raises(UnknownName):
        evaluate("doc.missing", {"doc": {}})


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "open('x')",
        "x.__class__",
        "[1, 2][0]",
        "lambda: 1",
        "x ** 999999",
    ],
)
def test_rejects_unsafe_constructs(expr):
    with pytest.raises(UnsafeExpression):
        evaluate(expr, {"x": 1})


def test_check_expression_accepts_rule_syntax():
    check_expression("ownership_record.present and x * 2 >= 1")


@pytest.mark.parametrize("expr", ["open('x')", "x.__class__", "x ** 2", "[1][0]"])
def test_check_expression_rejects_unsafe(expr):
    with pytest.raises(UnsafeExpression):
        check_expression(expr)


def test_names_in_lists_top_level_names_in_order():
    assert names_in("(land_value + assets_value) * solatium_rate + land_value") == [
        "land_value", "assets_value", "solatium_rate",
    ]
