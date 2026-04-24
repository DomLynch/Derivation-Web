from datetime import UTC, datetime

from derivation_web.core.hashing import content_hash, step_hash


def test_content_hash_is_stable():
    args = dict(
        kind="source",
        content_type="text/plain",
        body_text="hello",
        body_base64=None,
        metadata={"tag": "x"},
    )
    assert content_hash(**args) == content_hash(**args)


def test_content_hash_changes_with_body():
    base = dict(
        kind="source",
        content_type="text/plain",
        body_base64=None,
        metadata={},
    )
    assert content_hash(**base, body_text="a") != content_hash(**base, body_text="b")


def test_content_hash_changes_with_metadata():
    base = dict(
        kind="source",
        content_type="text/plain",
        body_text="a",
        body_base64=None,
    )
    assert content_hash(**base, metadata={"x": 1}) != content_hash(
        **base, metadata={"x": 2}
    )


def test_step_hash_is_stable():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    args = dict(
        step_type="summarize",
        input_artifact_ids=["a", "b"],
        output_artifact_id="c",
        target_artifact_id=None,
        actor_id="actor:1",
        method={"model": "x"},
        created_at=t,
    )
    assert step_hash(**args) == step_hash(**args)


def test_step_hash_input_order_is_semantic():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    base = dict(
        step_type="compare",
        output_artifact_id="c",
        target_artifact_id=None,
        actor_id="actor:1",
        method={},
        created_at=t,
    )
    a = step_hash(**base, input_artifact_ids=["a", "b"])
    b = step_hash(**base, input_artifact_ids=["b", "a"])
    assert a != b


def test_step_hash_target_artifact_id_matters():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    base = dict(
        step_type="challenge",
        input_artifact_ids=["evidence"],
        output_artifact_id="ch",
        actor_id="actor:1",
        method={},
        created_at=t,
    )
    a = step_hash(**base, target_artifact_id="claim_a")
    b = step_hash(**base, target_artifact_id="claim_b")
    none = step_hash(**base, target_artifact_id=None)
    assert a != b
    assert a != none
