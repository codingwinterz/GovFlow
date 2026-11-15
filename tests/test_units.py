import pytest

from app.units import UnknownUnit, to_sqm


@pytest.mark.parametrize(
    "value, unit, expected",
    [
        (500, "sqm", 500),
        (500, "Sq. M.", 500),
        (500, "square metres", 500),
        (1.5, "hectare", 15000),
        (1.5, "ha", 15000),
        (1, "acre", 4046.8564224),
        (1000, "sq ft", 92.90304),
    ],
)
def test_converts_to_square_metres(value, unit, expected):
    assert to_sqm(value, unit) == pytest.approx(expected)


def test_unknown_unit_raises():
    with pytest.raises(UnknownUnit):
        to_sqm(10, "bigha")
