"""Tests for EmailVecStore."""
import pytest

from emailpet.storage.email_vec_store import EmailVecStore


@pytest.fixture
def store(tmp_path):
    return EmailVecStore(tmp_path / "vec.db", dimensions=4)


def test_index_and_query_returns_nearest(store):
    store.index(1, [1.0, 0.0, 0.0, 0.0])
    store.index(2, [0.0, 1.0, 0.0, 0.0])
    store.index(3, [0.9, 0.1, 0.0, 0.0])
    results = store.query([1.0, 0.0, 0.0, 0.0], k=2)
    assert 1 in results
    assert 3 in results
    assert 2 not in results


def test_index_overwrites_existing(store):
    store.index(1, [1.0, 0.0, 0.0, 0.0])
    store.index(1, [0.0, 1.0, 0.0, 0.0])
    results = store.query([0.0, 1.0, 0.0, 0.0], k=1)
    assert results == [1]


def test_query_empty_store_returns_empty(store):
    assert store.query([1.0, 0.0, 0.0, 0.0], k=5) == []


def test_query_k_larger_than_count(store):
    store.index(1, [1.0, 0.0, 0.0, 0.0])
    results = store.query([1.0, 0.0, 0.0, 0.0], k=5)
    assert results == [1]
