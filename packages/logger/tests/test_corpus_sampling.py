"""Determinism guarantees the corpus rests on."""

from __future__ import annotations

from logger.corpora.sampling import ContentDigest, deterministic_sample

STREAM = [f"line-{i}" for i in range(1000)]


def _sample(seed: int, size: int | None = 50) -> list[tuple[int, str]]:
    return list(deterministic_sample(iter(STREAM), sample_size=size, seed=seed))


def test_same_seed_gives_identical_sample() -> None:
    assert _sample(7) == _sample(7)


def test_different_seed_gives_different_sample() -> None:
    assert _sample(7) != _sample(8)


def test_sample_is_returned_in_source_order() -> None:
    indices = [i for i, _ in _sample(7)]
    assert indices == sorted(indices)


def test_sample_size_is_exact() -> None:
    assert len(_sample(7, 50)) == 50


def test_items_match_their_source_index() -> None:
    for index, item in _sample(3, 100):
        assert item == STREAM[index]


def test_sample_larger_than_stream_keeps_everything() -> None:
    assert [item for _, item in _sample(7, 5000)] == STREAM


def test_none_sample_size_keeps_everything() -> None:
    assert [item for _, item in _sample(7, None)] == STREAM


def test_zero_sample_size_is_empty() -> None:
    assert _sample(7, 0) == []


def test_negative_sample_size_rejected() -> None:
    try:
        _sample(7, -1)
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_sampler_does_not_disturb_global_random() -> None:
    import random

    random.seed(99)
    before = [random.random() for _ in range(3)]
    random.seed(99)
    _sample(7)
    after = [random.random() for _ in range(3)]
    assert before == after


def test_content_digest_is_order_sensitive_and_stable() -> None:
    a, b = ContentDigest(), ContentDigest()
    a.update("x", None, "INFO")
    a.update("y", "2005-01-01T00:00:00+00:00", None)
    b.update("x", None, "INFO")
    b.update("y", "2005-01-01T00:00:00+00:00", None)
    assert a.hexdigest() == b.hexdigest()
    assert a.count == 2

    c = ContentDigest()
    c.update("y", "2005-01-01T00:00:00+00:00", None)
    c.update("x", None, "INFO")
    assert c.hexdigest() != a.hexdigest()


def test_content_digest_distinguishes_none_from_empty() -> None:
    a, b = ContentDigest(), ContentDigest()
    a.update("x", None)
    b.update("x", "")
    assert a.hexdigest() != b.hexdigest()
