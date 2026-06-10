"""The seedable, dependency-free isolation guard in conftest.py.

A given seed must produce a deterministic permutation of collected items so any
order-dependent failure can be reproduced exactly via E2E_TEST_SEED=<seed>.
"""
import importlib

conftest = importlib.import_module("conftest")


def test_seeded_order_is_deterministic_permutation():
    items = list(range(20))
    a = conftest._seeded_order(items, 42)
    b = conftest._seeded_order(items, 42)
    assert a == b                      # same seed -> same order
    assert sorted(a) == items          # a permutation, nothing lost
    assert a != items                  # actually reorders (seed 42 on 0..19)


def test_seeded_order_differs_across_seeds():
    items = list(range(20))
    assert conftest._seeded_order(items, 1) != conftest._seeded_order(items, 2)


def test_seeded_order_does_not_mutate_input():
    items = list(range(10))
    snapshot = list(items)
    conftest._seeded_order(items, 7)
    assert items == snapshot
