"""The known-good solution, as a contender: shows what a 100% row looks like. Uses no model."""
from pathlib import Path

Path("cart.py").write_text('''COUPONS = {"SAVE10": 0.10}


def total(prices, coupon=None):
    subtotal = sum(prices)
    if coupon is None:
        return subtotal
    if coupon not in COUPONS:
        raise ValueError(f"unknown coupon: {coupon}")
    return subtotal * (1 - COUPONS[coupon])
''')
