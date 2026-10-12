import pytest

from cart import total


def test_plain():
    assert total([10, 5]) == 15


def test_save10():
    assert total([100], coupon="SAVE10") == pytest.approx(90)


def test_unknown_coupon_raises():
    with pytest.raises(ValueError):
        total([1], coupon="BOGUS")


def test_empty_cart_with_coupon():
    assert total([], coupon="SAVE10") == 0
