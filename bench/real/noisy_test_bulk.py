import pytest
from cart import total


@pytest.mark.parametrize("n", range(1500))
def test_bulk_sum(n):
    assert total([n, 1]) == n + 1
