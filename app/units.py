"""Area unit conversion to square metres. Physical constants only, no scheme logic."""

import re

_SQM_PER_UNIT = {
    "sqm": 1.0,
    "m2": 1.0,
    "squaremetre": 1.0,
    "squaremeter": 1.0,
    "ha": 10_000.0,
    "hectare": 10_000.0,
    "acre": 4046.8564224,
    "sqft": 0.09290304,
    "squarefoot": 0.09290304,
    "squarefeet": 0.09290304,
}


class UnknownUnit(ValueError):
    """The area unit is not recognised; route to human review."""


def _normalise_unit(unit: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", unit.lower())
    return key[:-1] if key.endswith("s") and key[:-1] in _SQM_PER_UNIT else key


def to_sqm(value: float, unit: str) -> float:
    key = _normalise_unit(unit)
    if key not in _SQM_PER_UNIT:
        raise UnknownUnit(unit)
    return float(value) * _SQM_PER_UNIT[key]
