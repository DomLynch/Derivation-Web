"""Pure chain-walking logic. IO-free — callers supply lookup callables."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from derivation_web.core.models import Artifact, Step


@dataclass(frozen=True)
class ChainNode:
    artifact: Artifact
    producing_step: Step | None
    depth: int


def walk_provenance(
    *,
    root_artifact_id: str,
    get_artifact: Callable[[str], Artifact | None],
    get_producing_step: Callable[[str], Step | None],
    max_depth: int = 64,
) -> list[ChainNode]:
    """BFS backward from root. Root is depth 0.

    For each node, `producing_step` is the step whose output is that
    artifact (None for sources). Causal parents are both
    `input_artifact_ids` (evidence / sources consumed) and
    `target_artifact_id` (for challenge / revise, the thing being
    challenged or revised). Both edges are traversed. Cycles and
    over-deep chains are pruned.
    """
    nodes: list[ChainNode] = []
    seen: set[str] = set()
    frontier: list[tuple[str, int]] = [(root_artifact_id, 0)]

    while frontier:
        current_id, depth = frontier.pop(0)
        if current_id in seen or depth > max_depth:
            continue
        artifact = get_artifact(current_id)
        if artifact is None:
            continue
        seen.add(current_id)
        step = get_producing_step(current_id)
        nodes.append(
            ChainNode(artifact=artifact, producing_step=step, depth=depth)
        )
        if step is None:
            continue
        for input_id in step.input_artifact_ids:
            frontier.append((input_id, depth + 1))
        if step.target_artifact_id is not None:
            frontier.append((step.target_artifact_id, depth + 1))

    return nodes
