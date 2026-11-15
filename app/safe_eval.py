"""Safe evaluator for rule conditions and compensation formulas in YAML.

Only a whitelist of AST nodes is allowed: literals, list/tuple literals, names,
dotted access into dicts, arithmetic, comparisons (including `in` against a list),
boolean logic, and calls to the functions in FUNCTIONS only (one positional argument).
No other calls, methods, subscripts, comprehensions, lambdas, dunder access or
exponentiation. Never uses eval().
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

def _member(item: Any, container: Any) -> bool:
    if not isinstance(container, (list, tuple)):
        raise TypeError("`in` needs a list, e.g. x in ['a', 'b']")   # never substring matching
    return item in container


def _lower(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"lower() needs text, got {type(value).__name__}")
    return " ".join(value.split()).casefold()


FUNCTIONS = {"lower": _lower}   # the only callable names; taken from here, never from the namespace

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: _member,
    ast.NotIn: lambda item, container: not _member(item, container),
}


_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.List, ast.Tuple, ast.Call,
    ast.USub, ast.Not, ast.And, ast.Or,
    *_BIN_OPS, *_CMP_OPS,
)


def _parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpression(f"Invalid expression: {expr!r}") from exc


def _check_call(node: ast.Call, expr: str) -> None:
    if not (isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS):
        raise UnsafeExpression(f"Only {sorted(FUNCTIONS)} may be called in {expr!r}")
    if len(node.args) != 1 or node.keywords or isinstance(node.args[0], ast.Starred):
        raise UnsafeExpression(f"{node.func.id}() takes exactly one positional argument in {expr!r}")


def check_expression(expr: str) -> None:
    """Statically validate an expression without evaluating it (used at YAML load)."""
    for node in ast.walk(_parse(expr)):
        if isinstance(node, ast.Call):
            _check_call(node, expr)
        if not isinstance(node, _ALLOWED_NODES):
            raise UnsafeExpression(f"Construct not allowed in {expr!r}: {type(node).__name__}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsafeExpression(f"Private attribute not allowed in {expr!r}")


def names_in(expr: str) -> list[str]:
    """Top-level names an expression refers to, in order of first use."""
    tree = _parse(expr)
    functions = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    found = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in functions]
    found.sort(key=lambda n: n.col_offset)  # ast.walk is breadth-first; restore source order
    return list(dict.fromkeys(n.id for n in found))


def evaluate(expr: str, names: Mapping[str, Any]) -> Any:
    check_expression(expr)   # the whitelist is enforced on every evaluation, not only at load
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
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(_eval(e, names) for e in node.elts)
    if isinstance(node, ast.Call):
        _check_call(node, "call")
        return FUNCTIONS[node.func.id](_eval(node.args[0], names))
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
