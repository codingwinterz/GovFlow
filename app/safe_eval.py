"""Safe evaluator for rule conditions and compensation formulas in YAML.

Only a whitelist of AST nodes is allowed: literals, names, dotted access into
dicts, arithmetic, comparisons and boolean logic. No calls, subscripts,
lambdas, dunder access or exponentiation. Never uses eval().
"""

import ast
import operator
from typing import Any, Mapping


class UnsafeExpression(ValueError):
    """The expression uses a construct that is not allowed."""


class UnknownName(KeyError):
    """The expression refers to a name or field that is not available."""


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.USub, ast.Not, ast.And, ast.Or,
    *_BIN_OPS, *_CMP_OPS,
)


def _parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"Invalid expression: {expr!r}") from exc


def check_expression(expr: str) -> None:
    """Statically validate an expression without evaluating it (used at YAML load)."""
    for node in ast.walk(_parse(expr)):
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression(f"Construct not allowed in {expr!r}: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsafeExpression(f"Private attribute not allowed in {expr!r}")


def names_in(expr: str) -> list[str]:
    """Top-level names an expression refers to, in order of first use."""
    found = [n for n in ast.walk(_parse(expr)) if isinstance(n, ast.Name)]
    found.sort(key=lambda n: n.col_offset)  # ast.walk is breadth-first; restore source order
    return list(dict.fromkeys(n.id for n in found))


def evaluate(expr: str, names: Mapping[str, Any]) -> Any:
    return _eval(_parse(expr).body, names)


def _eval(node: ast.AST, names: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            raise UnknownName(node.id)
        return names[node.id]
    if isinstance(node, ast.Attribute):
        return _eval_attribute(node, names)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, names)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, names)
    if isinstance(node, ast.BoolOp):
        return _eval_boolop(node, names)
    if isinstance(node, ast.Compare):
        return _eval_compare(node, names)
    raise UnsafeExpression(f"Construct not allowed: {type(node).__name__}")


def _eval_attribute(node: ast.Attribute, names: Mapping[str, Any]) -> Any:
    if node.attr.startswith("_"):
        raise UnsafeExpression(f"Private attribute not allowed: {node.attr}")
    base = _eval(node.value, names)
    if not isinstance(base, Mapping):
        raise UnsafeExpression(f"Dotted access only works on records, not {type(base).__name__}")
    if node.attr not in base:
        raise UnknownName(node.attr)
    return base[node.attr]


def _eval_boolop(node: ast.BoolOp, names: Mapping[str, Any]) -> bool:
    values = (_eval(v, names) for v in node.values)
    if isinstance(node.op, ast.And):
        return all(values)
    return any(values)


def _eval_compare(node: ast.Compare, names: Mapping[str, Any]) -> bool:
    left = _eval(node.left, names)
    for op, right_node in zip(node.ops, node.comparators):
        if type(op) not in _CMP_OPS:
            raise UnsafeExpression(f"Comparison not allowed: {type(op).__name__}")
        right = _eval(right_node, names)
        if not _CMP_OPS[type(op)](left, right):
            return False
        left = right
    return True
