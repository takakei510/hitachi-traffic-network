from __future__ import annotations

from dataclasses import dataclass
import math
import re
from statistics import mean
from typing import Hashable, Mapping

import networkx as nx


EdgeId = tuple[Hashable, Hashable]


@dataclass(frozen=True)
class LaneInfo:
    raw_value: object
    total_lanes: float
    effective_lanes: float
    source: str
    is_oneway: bool


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
    lane_info: dict[EdgeId, LaneInfo]
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


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip().lower()
    return text in {"", "nan", "none", "null", "<na>"}


def parse_lane_count(value: object) -> float | None:
    """Parse OSM ``lanes`` values.

    Multiple numeric values such as ``"3,2"`` are interpreted as directional
    lane counts and summed, so ``"3,2"`` becomes five total lanes. Lists and
    other common separators are also accepted.
    """
    if _is_missing(value):
        return None

    if isinstance(value, (list, tuple, set)):
        parsed = [parse_lane_count(item) for item in value]
        numbers = [number for number in parsed if number is not None]
        return sum(numbers) if numbers else None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0.0 else None

    numbers = [float(token) for token in re.findall(r"\d+(?:\.\d+)?", str(value))]
    positive = [number for number in numbers if number > 0.0]
    return sum(positive) if positive else None


def _is_oneway(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not _is_missing(value):
        return float(value) != 0.0
    text = str(value).strip().lower()
    return text in {"yes", "true", "1", "-1", "t", "y"}


def _highway_name(value: object) -> str:
    if _is_missing(value):
        return "unknown"
    text = str(value).lower()
    for highway_type in (
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "residential",
        "unclassified",
        "living_street",
        "service",
    ):
        if highway_type in text:
            return highway_type
    return "unknown"


def infer_effective_lanes(highway: object) -> float:
    """Return a conservative per-direction lane estimate for missing data."""
    road_type = _highway_name(highway)
    if road_type in {"motorway", "trunk"}:
        return 2.0
    return 1.0


def get_lane_info(data: Mapping[str, object]) -> LaneInfo:
    raw_value = data.get("lanes")
    parsed_total = parse_lane_count(raw_value)
    oneway = _is_oneway(data.get("oneway", False))

    if parsed_total is None:
        effective = infer_effective_lanes(data.get("highway"))
        return LaneInfo(
            raw_value=raw_value,
            total_lanes=effective if oneway else effective * 2.0,
            effective_lanes=effective,
            source="highwayから推定",
            is_oneway=oneway,
        )

    effective = parsed_total if oneway else max(parsed_total / 2.0, 1.0)
    source = "OSM lanes"
    if isinstance(raw_value, str) and len(re.findall(r"\d+(?:\.\d+)?", raw_value)) > 1:
        source = "OSM lanes複数値を合計"
    if not oneway:
        source += "・双方向補正"

    return LaneInfo(
        raw_value=raw_value,
        total_lanes=parsed_total,
        effective_lanes=effective,
        source=source,
        is_oneway=oneway,
    )


def build_lane_info(graph: nx.Graph) -> dict[EdgeId, LaneInfo]:
    return {
        canonical_edge(graph, u, v): get_lane_info(data)
        for u, v, data in graph.edges(data=True)
    }


def compute_edge_load(
    graph: nx.Graph,
    *,
    normalized: bool = True,
    sample_size: int | None = None,
    seed: int | None = 42,
) -> dict[EdgeId, float]:
    """Compute edge betweenness using road length as path cost."""
    if graph.number_of_edges() == 0:
        return {}

    node_count = graph.number_of_nodes()
    k = None
    if sample_size is not None and sample_size > 0 and sample_size < node_count:
        k = sample_size

    centrality = nx.edge_betweenness_centrality(
        graph,
        k=k,
        normalized=normalized,
        weight="length",
        seed=seed,
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
    length_weight: float = 0.5,
    lane_weight: float = 0.5,
    use_lane_correction: bool = True,
) -> dict[EdgeId, float]:
    """Build road capacities with optional road-length and lane corrections.

    C_e = L_e(0)(1+alpha) f_length f_lanes

    f_length = 1 + w_length max(length/mean_length - 1, 0)
    f_lanes  = 1 + w_lanes max(effective_lanes - 1, 0)

    The factors never reduce capacity below the ordinary ``(1+alpha)`` margin.
    Missing lane values are conservatively inferred from ``highway``.
    """
    if alpha < 0.0:
        raise ValueError("alpha must be non-negative")
    if length_weight < 0.0:
        raise ValueError("length_weight must be non-negative")
    if lane_weight < 0.0:
        raise ValueError("lane_weight must be non-negative")

    lengths = [_edge_length(data) for _, _, data in graph.edges(data=True)]
    mean_length = mean(lengths) if lengths else 1.0
    capacities: dict[EdgeId, float] = {}

    for u, v, data in graph.edges(data=True):
        edge = canonical_edge(graph, u, v)
        relative_length = _edge_length(data) / mean_length
        length_bonus = 1.0 + length_weight * max(relative_length - 1.0, 0.0)
        lane_bonus = 1.0
        if use_lane_correction:
            lane_info = get_lane_info(data)
            lane_bonus += lane_weight * max(lane_info.effective_lanes - 1.0, 0.0)

        capacities[edge] = (
            float(initial_loads.get(edge, 0.0))
            * (1.0 + alpha)
            * length_bonus
            * lane_bonus
        )
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
    length_weight: float = 0.5,
    lane_weight: float = 0.5,
    use_lane_correction: bool = True,
    overload_threshold: float = 1.2,
    sample_size: int | None = None,
    seed: int | None = 42,
    max_steps: int | None = None,
) -> RoadCascadeResult:
    """Run an edge-based cascade while preserving the original graph.

    An active road becomes unavailable only when its load ratio is greater than
    ``overload_threshold``. For example, 1.2 allows a temporary 20% excess.
    """
    if overload_threshold < 1.0:
        raise ValueError("overload_threshold must be at least 1.0")

    current = graph.copy()
    initial_loads = compute_edge_load(current, sample_size=sample_size, seed=seed)
    capacities = build_length_adjusted_capacities(
        current,
        initial_loads,
        alpha=alpha,
        length_weight=length_weight,
        lane_weight=lane_weight,
        use_lane_correction=use_lane_correction,
    )
    lane_info = build_lane_info(current)

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
        loads = compute_edge_load(current, sample_size=sample_size, seed=seed)
        ratios = _load_ratios(current, loads, capacities)
        overloaded = {
            edge for edge, ratio in ratios.items() if ratio > overload_threshold
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
        lane_info=lane_info,
        steps=tuple(steps),
    )
