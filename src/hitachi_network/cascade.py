from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Mapping

import networkx as nx


@dataclass(frozen=True)
class CascadeResult:
    failed_by_step: list[set[Hashable]]
    surviving_graph: nx.Graph

    @property
    def all_failed(self) -> set[Hashable]:
        return set().union(*self.failed_by_step) if self.failed_by_step else set()


def run_node_cascade(
    graph: nx.Graph,
    initial_load: Mapping[Hashable, float],
    attacked_nodes: set[Hashable],
    *,
    tolerance: float = 0.2,
    recompute_load=None,
    max_steps: int = 100,
) -> CascadeResult:
    """Run a generic node-overload cascade.

    Capacity is ``initial_load[node] * (1 + tolerance)``. After each removal,
    ``recompute_load(current_graph)`` must return the updated node loads.

    Keeping load calculation outside this function lets the team plug in
    betweenness-based load, OD traffic, or another congestion model without
    rewriting the cascade control logic.
    """
    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if recompute_load is None:
        raise ValueError("recompute_load function is required")

    capacities = {
        node: float(initial_load.get(node, 0.0)) * (1.0 + tolerance)
        for node in graph.nodes
    }
    current = graph.copy()
    failed_by_step: list[set[Hashable]] = []

    first = set(attacked_nodes) & set(current.nodes)
    if first:
        current.remove_nodes_from(first)
        failed_by_step.append(first)

    for _ in range(max_steps):
        loads = recompute_load(current)
        overloaded = {
            node
            for node in current.nodes
            if float(loads.get(node, 0.0)) > capacities.get(node, 0.0)
        }
        if not overloaded:
            break
        current.remove_nodes_from(overloaded)
        failed_by_step.append(overloaded)
    else:
        raise RuntimeError("Cascade did not converge before max_steps")

    return CascadeResult(failed_by_step, current)
