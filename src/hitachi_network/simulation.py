from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Hashable, Mapping

import networkx as nx
import pandas as pd

from .cascade import CascadeResult, run_node_cascade


LoadMap = Mapping[Hashable, float]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    attack_nodes: list[Hashable]
    load_model: str
    initial_load: dict[Hashable, float]
    cascade: CascadeResult
    step_records: list[dict[str, object]]
    summary: dict[str, object]


def project_road_graph(graph: nx.Graph) -> nx.Graph:
    """Collapse multiedges into a simple graph for load and cascade analysis."""
    simple = nx.DiGraph() if graph.is_directed() else nx.Graph()
    simple.add_nodes_from(graph.nodes(data=True))
    simple.graph.update(graph.graph)

    if graph.is_multigraph():
        for u, v, data in graph.edges(data=True):
            if simple.has_edge(u, v):
                current_length = float(simple[u][v].get("length", float("inf")))
                candidate_length = float(data.get("length", float("inf")))
                if candidate_length < current_length:
                    simple[u][v].clear()
                    simple[u][v].update(data)
            else:
                simple.add_edge(u, v, **data)
        return simple

    simple.add_edges_from(graph.edges(data=True))
    return simple


def compute_node_load(
    graph: nx.Graph,
    *,
    model: str = "betweenness",
    sample_size: int = 64,
    seed: int | None = 42,
) -> dict[Hashable, float]:
    """Compute a node load map for the current graph."""
    if graph.number_of_nodes() == 0:
        return {}

    if model == "degree":
        return {node: float(degree) for node, degree in graph.degree()}

    if model != "betweenness":
        raise ValueError(f"Unsupported load model: {model}")

    node_count = graph.number_of_nodes()
    if sample_size <= 0 or node_count <= sample_size:
        centrality = nx.betweenness_centrality(graph, weight="length", normalized=True)
    else:
        centrality = nx.betweenness_centrality(
            graph,
            k=sample_size,
            weight="length",
            normalized=True,
            seed=seed,
        )
    return {node: float(value) for node, value in centrality.items()}


def select_high_load_nodes(loads: LoadMap, attack_count: int) -> list[Hashable]:
    if attack_count <= 0:
        raise ValueError("attack_count must be positive")
    if attack_count > len(loads):
        attack_count = len(loads)
    ordered = sorted(loads.items(), key=lambda item: (-float(item[1]), repr(item[0])))
    return [node for node, _ in ordered[:attack_count]]


def select_random_nodes(
    nodes: list[Hashable],
    attack_count: int,
    *,
    seed: int | None = None,
) -> list[Hashable]:
    if attack_count <= 0:
        raise ValueError("attack_count must be positive")
    if attack_count > len(nodes):
        attack_count = len(nodes)
    rng = random.Random(seed)
    return rng.sample(nodes, attack_count)


def _largest_component_size(graph: nx.Graph) -> int:
    if graph.number_of_nodes() == 0:
        return 0
    if graph.is_directed():
        components = nx.weakly_connected_components(graph)
    else:
        components = nx.connected_components(graph)
    return max((len(component) for component in components), default=0)


def _build_step_records(name: str, result: CascadeResult) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    cumulative_failed: set[Hashable] = set()
    total_steps = len(result.failed_by_step)

    for step_index, failed_nodes in enumerate(result.failed_by_step, start=1):
        cumulative_failed |= set(failed_nodes)
        records.append(
            {
                "scenario": name,
                "step": step_index,
                "newly_failed": len(failed_nodes),
                "cumulative_failed": len(cumulative_failed),
                "remaining_nodes": result.surviving_graph.number_of_nodes(),
                "remaining_edges": result.surviving_graph.number_of_edges(),
                "failed_nodes": json.dumps(sorted(repr(node) for node in failed_nodes)),
                "total_steps": total_steps,
            }
        )

    if not records:
        records.append(
            {
                "scenario": name,
                "step": 0,
                "newly_failed": 0,
                "cumulative_failed": 0,
                "remaining_nodes": result.surviving_graph.number_of_nodes(),
                "remaining_edges": result.surviving_graph.number_of_edges(),
                "failed_nodes": "[]",
                "total_steps": 0,
            }
        )

    return records


def _build_summary(
    *,
    name: str,
    graph: nx.Graph,
    attacked_nodes: list[Hashable],
    result: CascadeResult,
) -> dict[str, object]:
    failed_nodes = sorted(repr(node) for node in result.all_failed)
    return {
        "scenario": name,
        "initial_nodes": graph.number_of_nodes(),
        "initial_edges": graph.number_of_edges(),
        "attacked_count": len(attacked_nodes),
        "failed_count": len(result.all_failed),
        "failed_fraction": (len(result.all_failed) / graph.number_of_nodes()) if graph.number_of_nodes() else 0.0,
        "surviving_nodes": result.surviving_graph.number_of_nodes(),
        "surviving_edges": result.surviving_graph.number_of_edges(),
        "cascade_steps": len(result.failed_by_step),
        "largest_component_size": _largest_component_size(result.surviving_graph),
        "attacked_nodes": [repr(node) for node in attacked_nodes],
        "failed_nodes": failed_nodes,
    }


def run_scenario(
    graph: nx.Graph,
    *,
    name: str,
    attacked_nodes: list[Hashable],
    load_model: str = "betweenness",
    sample_size: int = 64,
    seed: int | None = 42,
    tolerance: float = 0.2,
) -> ScenarioResult:
    simple_graph = project_road_graph(graph)
    initial_load = compute_node_load(
        simple_graph,
        model=load_model,
        sample_size=sample_size,
        seed=seed,
    )

    def recompute_load(current_graph: nx.Graph) -> dict[Hashable, float]:
        return compute_node_load(
            current_graph,
            model=load_model,
            sample_size=sample_size,
            seed=seed,
        )

    cascade = run_node_cascade(
        simple_graph,
        initial_load,
        set(attacked_nodes),
        tolerance=tolerance,
        recompute_load=recompute_load,
    )

    step_records = _build_step_records(name, cascade)
    summary = _build_summary(
        name=name,
        graph=simple_graph,
        attacked_nodes=attacked_nodes,
        result=cascade,
    )
    return ScenarioResult(
        name=name,
        attack_nodes=attacked_nodes,
        load_model=load_model,
        initial_load=initial_load,
        cascade=cascade,
        step_records=step_records,
        summary=summary,
    )


def run_comparison(
    graph: nx.Graph,
    *,
    attack_count: int = 10,
    seed: int | None = 42,
    load_model: str = "betweenness",
    sample_size: int = 64,
    tolerance: float = 0.2,
) -> list[ScenarioResult]:
    simple_graph = project_road_graph(graph)
    initial_load = compute_node_load(
        simple_graph,
        model=load_model,
        sample_size=sample_size,
        seed=seed,
    )
    nodes = list(simple_graph.nodes)

    high_load_nodes = select_high_load_nodes(initial_load, attack_count)
    random_nodes = select_random_nodes(nodes, attack_count, seed=seed)

    def run(attacked_nodes: list[Hashable], name: str) -> ScenarioResult:
        cascade = run_node_cascade(
            simple_graph,
            initial_load,
            set(attacked_nodes),
            tolerance=tolerance,
            recompute_load=lambda current_graph: compute_node_load(
                current_graph,
                model=load_model,
                sample_size=sample_size,
                seed=seed,
            ),
        )
        return ScenarioResult(
            name=name,
            attack_nodes=attacked_nodes,
            load_model=load_model,
            initial_load=initial_load,
            cascade=cascade,
            step_records=_build_step_records(name, cascade),
            summary=_build_summary(
                name=name,
                graph=simple_graph,
                attacked_nodes=attacked_nodes,
                result=cascade,
            ),
        )

    return [
        run(random_nodes, "random_failure"),
        run(high_load_nodes, "high_load_failure"),
    ]


def write_comparison_outputs(
    results: list[ScenarioResult],
    output_dir: str | Path,
    *,
    graph_title: str = "Hitachi cascade comparison",
) -> dict[str, Path]:
    from .plotting import plot_cascade_comparison

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = [result.summary for result in results]
    step_rows = [row for result in results for row in result.step_records]
    report = {
        "scenarios": [
            {
                **asdict(result),
                "cascade": {
                    "failed_by_step": [
                        [repr(node) for node in failed_nodes]
                        for failed_nodes in result.cascade.failed_by_step
                    ],
                    "surviving_graph_nodes": result.cascade.surviving_graph.number_of_nodes(),
                    "surviving_graph_edges": result.cascade.surviving_graph.number_of_edges(),
                },
            }
            for result in results
        ]
    }

    summary_path = output_dir / "cascade_summary.csv"
    steps_path = output_dir / "cascade_steps.csv"
    json_path = output_dir / "cascade_results.json"
    png_path = output_dir / "cascade_comparison.png"

    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    pd.DataFrame(step_rows).to_csv(steps_path, index=False)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_cascade_comparison(results, png_path, title=graph_title)

    return {
        "summary_csv": summary_path,
        "steps_csv": steps_path,
        "json": json_path,
        "png": png_path,
    }
