from derivation_web.core.canonical import canonicalize


def test_key_order_is_deterministic():
    assert canonicalize({"b": 1, "a": 2}) == canonicalize({"a": 2, "b": 1})


def test_no_whitespace():
    assert canonicalize({"x": 1, "y": "foo"}) == b'{"x":1,"y":"foo"}'


def test_nested_objects():
    a = canonicalize({"outer": {"b": 2, "a": 1}})
    b = canonicalize({"outer": {"a": 1, "b": 2}})
    assert a == b


def test_utf8():
    assert canonicalize({"x": "é"}) == '{"x":"é"}'.encode()


def test_nan_rejected():
    import math

    import pytest

    with pytest.raises(ValueError):
        canonicalize({"x": math.nan})
