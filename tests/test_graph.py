from datetime import UTC, datetime

from derivation_web.core.graph import walk_provenance
from derivation_web.core.models import Artifact, ArtifactKind, Step, StepType


def _art(aid: str, kind: ArtifactKind = ArtifactKind.SOURCE) -> Artifact:
    return Artifact(
        id=aid,
        kind=kind,
        content_type="text/plain",
        body_text=aid,
        body_base64=None,
        metadata={},
        content_hash="x" * 64,
        actor_id="a",
        created_at=datetime.now(UTC),
    )


def _step(
    sid: str,
    inputs: list[str],
    output: str,
    step_type: StepType = StepType.SUMMARIZE,
) -> Step:
    return Step(
        id=sid,
        step_type=step_type,
        input_artifact_ids=inputs,
        output_artifact_id=output,
        actor_id="a",
        method={},
        step_hash="y" * 64,
        signature_b64=None,
        created_at=datetime.now(UTC),
    )


def test_single_source_has_no_producing_step():
    artifacts = {"a": _art("a")}
    nodes = walk_provenance(
        root_artifact_id="a",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda _: None,
    )
    assert [n.artifact.id for n in nodes] == ["a"]
    assert nodes[0].producing_step is None
    assert nodes[0].depth == 0


def test_two_sources_feed_one_claim():
    a1, a2 = _art("a1"), _art("a2")
    c = _art("c", ArtifactKind.CLAIM)
    artifacts = {"a1": a1, "a2": a2, "c": c}
    steps = {"c": _step("s1", ["a1", "a2"], "c")}
    nodes = walk_provenance(
        root_artifact_id="c",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda aid: steps.get(aid),
    )
    ids = [n.artifact.id for n in nodes]
    assert ids[0] == "c"
    assert set(ids[1:]) == {"a1", "a2"}
    assert nodes[0].depth == 0
    assert all(n.depth == 1 for n in nodes[1:])
    assert nodes[0].producing_step is not None
    assert nodes[0].producing_step.id == "s1"


def test_cycle_is_pruned():
    a, b = _art("a"), _art("b")
    artifacts = {"a": a, "b": b}
    steps = {"a": _step("sa", ["b"], "a"), "b": _step("sb", ["a"], "b")}
    nodes = walk_provenance(
        root_artifact_id="a",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda aid: steps.get(aid),
    )
    assert {n.artifact.id for n in nodes} == {"a", "b"}


def test_walk_from_challenge_reaches_target_claim():
    src = _art("src")
    claim = _art("claim", ArtifactKind.CLAIM)
    ev = _art("ev")
    ch = _art("ch", ArtifactKind.CHALLENGE)
    artifacts = {"src": src, "claim": claim, "ev": ev, "ch": ch}
    claim_step = _step("s_claim", ["src"], "claim")
    ch_step = Step(
        id="s_ch",
        step_type=StepType.CHALLENGE,
        input_artifact_ids=["ev"],
        output_artifact_id="ch",
        target_artifact_id="claim",
        actor_id="a",
        method={},
        step_hash="y" * 64,
        signature_b64=None,
        created_at=datetime.now(UTC),
    )
    steps = {"claim": claim_step, "ch": ch_step}
    nodes = walk_provenance(
        root_artifact_id="ch",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda aid: steps.get(aid),
    )
    ids = {n.artifact.id for n in nodes}
    # challenge is root; evidence (input) and claim (target) are depth 1;
    # source reached transitively via the claim's producing step.
    assert ids == {"ch", "ev", "claim", "src"}
    # evidence and target are both depth-1 parents of the challenge
    by_id = {n.artifact.id: n.depth for n in nodes}
    assert by_id["ch"] == 0
    assert by_id["ev"] == 1
    assert by_id["claim"] == 1
    assert by_id["src"] == 2


def test_walk_from_claim_does_not_reach_downstream_challenge():
    claim = _art("claim", ArtifactKind.CLAIM)
    src = _art("src")
    ch = _art("ch", ArtifactKind.CHALLENGE)
    ev = _art("ev")
    artifacts = {"claim": claim, "src": src, "ch": ch, "ev": ev}
    steps = {
        "claim": _step("s_claim", ["src"], "claim"),
        "ch": Step(
            id="s_ch",
            step_type=StepType.CHALLENGE,
            input_artifact_ids=["ev"],
            output_artifact_id="ch",
            target_artifact_id="claim",
            actor_id="a",
            method={},
            step_hash="y" * 64,
            signature_b64=None,
            created_at=datetime.now(UTC),
        ),
    }
    nodes = walk_provenance(
        root_artifact_id="claim",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda aid: steps.get(aid),
    )
    ids = {n.artifact.id for n in nodes}
    # walking backward from claim reaches its sources only; the challenge
    # is causally downstream of the claim and must not appear in its chain.
    assert ids == {"claim", "src"}


def test_max_depth_is_respected():
    artifacts = {f"n{i}": _art(f"n{i}") for i in range(10)}
    steps = {f"n{i}": _step(f"s{i}", [f"n{i + 1}"], f"n{i}") for i in range(9)}
    nodes = walk_provenance(
        root_artifact_id="n0",
        get_artifact=lambda aid: artifacts.get(aid),
        get_producing_step=lambda aid: steps.get(aid),
        max_depth=3,
    )
    assert len(nodes) == 4  # n0..n3
