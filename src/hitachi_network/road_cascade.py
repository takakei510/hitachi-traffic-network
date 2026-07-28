from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Hashable, Mapping

import networkx as nx


EdgeId = tuple[Hashable, Hashable]


@dataclass(frozen=True)
class RoadCascadeStep:
    step_index: int
    failed_edges: tuple[EdgeId, ...]
    cumulative_failed_edges: tuple[EdgeId, ...]
    loads: dict[EdgeId, float]
    capacities: dict[EdgeId, float]
    load_ratios: dict[EdgeId, float]
    remaining_edges: int
    largest_component_size: int


@dataclass(frozen=True)
class RoadCascadeResult:
    failed_by_step: tuple[tuple[EdgeId, ...], ...]
    surviving_graph: nx.Graph
    initial_loads: dict[EdgeId, float]
    capacities: dict[EdgeId, float]
    steps: tuple[RoadCascadeStep, ...]

    @property
    def all_failed_edges(self) -> set[EdgeId]:
        failed: set[EdgeId] = set()
        for edges in self.failed_by_step:
            failed.update(edges)
        return failed


def canonical_edge(graph: nx.Graph, u: Hashable, v: Hashable) -> EdgeId:
    if graph.is_directed():
        return (u, v)
    return (u, v) if repr(u) <= repr(v) else (v, u)


def _edge_length(data: Mapping[str, object]) -> float:
    try:
        value = float(data.get("length", 1.0))
    except (TypeError, ValueError):
        value = 1.0
    return max(value, 1e-9)


def compute_edge_load(
    graph: nx.Graph,
    *,
    normalized: bool = True,
) -> dict[EdgeId, float]:
    """Compute edge betweenness centrality using road length as path cost."""
    if graph.number_of_edges() == 0:
        return {}
    centrality = nx.edge_betweenness_centrality(
        graph,
        normalized=normalized,
        weight="length",
    )
    return {
        canonical_edge(graph, u, v): float(value)
        for (u, v), value in centrality.items()
    }


def build_length_adjusted_capacities(
    graph: nx.Graph,
    initial_loads: Mapping[EdgeId, float],
    *,
    alpha: float = 0.2,
) -> dict[EdgeId, float]:
    """Build C_e=(1+alpha)L_e(0)(length_e/mean_length)."""
    if alpha < 0.0:
        raise ValueError("alpha must be non-negative")
    lengths = [_edge_length(data) for _, _, data in graph.edges(data=True)]
    mean_length = mean(lengths) if lengths else 1.0
    capacities: dict[EdgeId, float] = {}
    for u, v, data in graph.edges(data=True):
        edge = canonical_edge(graph, u, v)
        length_factor = _edge_length(data) / mean_length
        capacities[edge] = float(initial_loads.get(edge, 0.0)) * (1.0 + alpha) * length_factor
    return capacities


def _load_ratios(
    graph: nx.Graph,
    loads: Mapping[EdgeId, float],
    capacities: Mapping[EdgeId, float],
) -> dict[EdgeId, float]:
    ratios: dict[EdgeId, float] = {}
    for u, v in graph.edges():
        edge = canonical_edge(graph, u, v)
        load = float(loads.get(edge, 0.0))
        capacity = float(capacities.get(edge, 0.0))
        ratios[edge] = load / capacity if capacity > 0.0 else (float("inf") if load > 0.0 else 0.0)
    return ratios


def _largest_component_size(graph: nx.Graph) -> int:
    if graph.number_of_nodes() == 0:
        return 0
    components = nx.weakly_connected_components(graph) if graph.is_directed() else nx.connected_components(graph)
    return max((len(component) for component in components), default=0)


def run_road_capacity_cascade(
    graph: nx.Graph,
    *,
    attacked_edges: list[EdgeId],
    alpha: float = 0.2,
    max_steps: int | None = None,
) -> RoadCascadeResult:
    """Run an edge-based cascade while preserving the original graph.

    Capacity is based on initial edge betweenness and corrected by relative road length:
    C_e=(1+alpha)L_e(0)(length_e/mean_length).
    """
    current = graph.copy()
    initial_loads = compute_edge_load(current)
    capacities = build_length_adjusted_capacities(current, initial_loads, alpha=alpha)

    attacked: set[EdgeId] = set()
    for u, v in attacked_edges:
        edge = canonical_edge(current, u, v)
        if current.has_edge(*edge):
            attacked.add(edge)

    current.remove_edges_from(attacked)
    failed_by_step: list[tuple[EdgeId, ...]] = [tuple(sorted(attacked, key=repr))]
    cumulative_failed: set[EdgeId] = set(attacked)
    steps: list[RoadCascadeStep] = []

    initial_ratios = _load_ratios(current, initial_loads, capacities)
    steps.append(
        RoadCascadeStep(
            step_index=0,
            failed_edges=failed_by_step[0],
            cumulative_failed_edges=tuple(sorted(cumulative_failed, key=repr)),
            loads=dict(initial_loads),
            capacities=dict(capacities),
            load_ratios=initial_ratios,
            remaining_edges=current.number_of_edges(),
            largest_component_size=_largest_component_size(current),
        )
    )

    step_index = 0
    while current.number_of_edges() > 0:
        if max_steps is not None and step_index >= max_steps:
            break
        loads = compute_edge_load(current)
        ratios = _load_ratios(current, loads, capacities)
        overloaded = {
            edge
            for edge, ratio in ratios.items()
            if ratio > 1.0
        }
        if not overloaded:
            break

        step_index += 1
        current.remove_edges_from(overloaded)
        cumulative_failed.update(overloaded)
        failed_step = tuple(sorted(overloaded, key=repr))
        failed_by_step.append(failed_step)
        steps.append(
            RoadCascadeStep(
                step_index=step_index,
                failed_edges=failed_step,
                cumulative_failed_edges=tuple(sorted(cumulative_failed, key=repr)),
                loads=dict(loads),
                capacities=dict(capacities),
                load_ratios=ratios,
                remaining_edges=current.number_of_edges(),
                largest_component_size=_largest_component_size(current),
            )
        )

    return RoadCascadeResult(
        failed_by_step=tuple(failed_by_step),
        surviving_graph=current,
        initial_loads=initial_loads,
        capacities=capacities,
        steps=tuple(steps),
    )
