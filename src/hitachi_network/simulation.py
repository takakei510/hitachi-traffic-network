from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Hashable, Mapping, Sequence

import networkx as nx
import pandas as pd

from .cascade import CascadeResult, run_node_cascade


LoadMap = Mapping[Hashable, float]


@dataclass(frozen=True)
class TrialResult:
    scenario: str
    trial_index: int
    attack_nodes: list[Hashable]
    load_model: str
    alpha: float
    sample_size: int
    seed: int | None
    initial_load: dict[Hashable, float]
    cascade: CascadeResult
    step_records: list[dict[str, object]]
    summary: dict[str, object]


@dataclass(frozen=True)
class ComparisonResult:
    parameters: dict[str, object]
    random_trials: list[TrialResult]
    high_load: TrialResult
    random_summary: dict[str, object]
    high_load_summary: dict[str, object]
    trial_summaries: list[dict[str, object]]
    step_records: list[dict[str, object]]


def project_road_graph(graph: nx.Graph) -> nx.Graph:
    """Collapse multiedges into a simple graph for load and cascade analysis."""
    simple = nx.DiGraph() if graph.is_directed() else nx.Graph()
    simple.add_nodes_from(graph.nodes(data=True))
    simple.graph.update(graph.graph)

    if graph.is_multigraph():
        for u, v, data in graph.edges(data=True):
            if u == v:
                continue
            if simple.has_edge(u, v):
                current_length = float(simple[u][v].get("length", float("inf")))
                candidate_length = float(data.get("length", float("inf")))
                if candidate_length < current_length:
                    simple[u][v].clear()
                    simple[u][v].update(data)
            else:
                simple.add_edge(u, v, **data)
    else:
        for u, v, data in graph.edges(data=True):
            if u == v:
                continue
            simple.add_edge(u, v, **data)

    simple.remove_edges_from(list(nx.selfloop_edges(simple)))
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
    nodes: Sequence[Hashable],
    attack_count: int,
    *,
    seed: int | None = None,
) -> list[Hashable]:
    if attack_count <= 0:
        raise ValueError("attack_count must be positive")
    population = list(nodes)
    if attack_count > len(population):
        attack_count = len(population)
    rng = random.Random(seed)
    return rng.sample(population, attack_count)


def _largest_component_size(graph: nx.Graph) -> int:
    if graph.number_of_nodes() == 0:
        return 0
    if graph.is_directed():
        components = nx.weakly_connected_components(graph)
    else:
        components = nx.connected_components(graph)
    return max((len(component) for component in components), default=0)


def _max_load_ratio(
    loads: Mapping[Hashable, float],
    capacities: Mapping[Hashable, float],
    nodes: Sequence[Hashable],
) -> float:
    ratios: list[float] = []
    for node in nodes:
        capacity = float(capacities.get(node, 0.0))
        load = float(loads.get(node, 0.0))
        if capacity == 0.0:
            ratios.append(math.inf if load > 0.0 else 0.0)
        else:
            ratios.append(load / capacity)
    return max(ratios, default=0.0)


def _make_step_record(
    *,
    scenario: str,
    trial_index: int,
    cascade_step: int,
    current_graph: nx.Graph,
    loads: Mapping[Hashable, float],
    capacities: Mapping[Hashable, float],
    newly_failed_nodes: Sequence[Hashable],
    cumulative_failed_count: int,
) -> dict[str, object]:
    return {
        "scenario": scenario,
        "trial_index": trial_index,
        "cascade_step": cascade_step,
        "remaining_nodes": current_graph.number_of_nodes(),
        "largest_component_size": _largest_component_size(current_graph),
        "newly_failed_count": len(newly_failed_nodes),
        "cumulative_failed_count": cumulative_failed_count,
        "newly_failed_nodes": json.dumps([repr(node) for node in newly_failed_nodes], ensure_ascii=False),
        "max_load_ratio": _max_load_ratio(loads, capacities, current_graph.nodes),
    }


def _initial_trial_summary(
    *,
    scenario: str,
    trial_index: int,
    graph: nx.Graph,
    attack_nodes: Sequence[Hashable],
    alpha: float,
    load_model: str,
    sample_size: int,
    seed: int | None,
    result: CascadeResult,
) -> dict[str, object]:
    return {
        "scenario": scenario,
        "trial_index": trial_index,
        "alpha": alpha,
        "attack_count": len(attack_nodes),
        "attack_nodes": list(attack_nodes),
        "load_model": load_model,
        "sample_size": sample_size,
        "seed": seed,
        "initial_nodes": graph.number_of_nodes(),
        "initial_edges": graph.number_of_edges(),
        "final_surviving_nodes": result.surviving_graph.number_of_nodes(),
        "final_largest_component_size": _largest_component_size(result.surviving_graph),
        "failed_count": len(result.all_failed),
        "failed_fraction": (len(result.all_failed) / graph.number_of_nodes()) if graph.number_of_nodes() else 0.0,
        "cascade_steps": max(len(result.failed_by_step) - 1, 0),
    }


def _summarize_numeric(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    if len(values) == 1:
        return {"mean": float(values[0]), "std": 0.0}
    return {"mean": float(mean(values)), "std": float(stdev(values))}


def run_scenario(
    graph: nx.Graph,
    *,
    name: str,
    attacked_nodes: list[Hashable],
    load_model: str = "betweenness",
    sample_size: int = 64,
    seed: int | None = 42,
    alpha: float = 0.2,
) -> TrialResult:
    simple_graph = project_road_graph(graph)
    initial_load = compute_node_load(
        simple_graph,
        model=load_model,
        sample_size=sample_size,
        seed=seed,
    )
    capacities = {
        node: float(initial_load.get(node, 0.0)) * (1.0 + alpha)
        for node in simple_graph.nodes
    }

    current = simple_graph.copy()
    failed_by_step: list[set[Hashable]] = []
    attacked = [node for node in attacked_nodes if node in current]
    attacked_set = set(attacked)
    current.remove_nodes_from(attacked_set)
    if attacked_set:
        failed_by_step.append(attacked_set)

    step_records: list[dict[str, object]] = []
    cumulative_failed_count = len(attacked_set)
    step_records.append(
        _make_step_record(
            scenario=name,
            trial_index=1,
            cascade_step=0,
            current_graph=current,
            loads=initial_load,
            capacities=capacities,
            newly_failed_nodes=attacked,
            cumulative_failed_count=cumulative_failed_count,
        )
    )

    def recompute_load(current_graph: nx.Graph) -> dict[Hashable, float]:
        return compute_node_load(
            current_graph,
            model=load_model,
            sample_size=sample_size,
            seed=seed,
        )

    cascade_step = 0
    while True:
        loads = recompute_load(current)
        overloaded = {
            node
            for node in current.nodes
            if float(loads.get(node, 0.0)) > capacities.get(node, 0.0)
        }
        if not overloaded:
            break
        cascade_step += 1
        current.remove_nodes_from(overloaded)
        failed_by_step.append(overloaded)
        cumulative_failed_count += len(overloaded)
        step_records.append(
            _make_step_record(
                scenario=name,
                trial_index=1,
                cascade_step=cascade_step,
                current_graph=current,
                loads=loads,
                capacities=capacities,
                newly_failed_nodes=sorted(overloaded, key=repr),
                cumulative_failed_count=cumulative_failed_count,
            )
        )

    trial_result = TrialResult(
        scenario=name,
        trial_index=1,
        attack_nodes=attacked,
        load_model=load_model,
        alpha=alpha,
        sample_size=sample_size,
        seed=seed,
        initial_load=initial_load,
        cascade=CascadeResult(failed_by_step=failed_by_step, surviving_graph=current),
        step_records=step_records,
        summary=_initial_trial_summary(
            scenario=name,
            trial_index=1,
            graph=simple_graph,
            attack_nodes=attacked,
            alpha=alpha,
            load_model=load_model,
            sample_size=sample_size,
            seed=seed,
            result=CascadeResult(failed_by_step=failed_by_step, surviving_graph=current),
        ),
    )
    return trial_result


def _random_attack_seed(seed: int | None, trial_index: int) -> int | None:
    if seed is None:
        return None
    return seed + trial_index


def _run_trial(
    *,
    graph: nx.Graph,
    initial_load: Mapping[Hashable, float],
    scenario: str,
    trial_index: int,
    attacked_nodes: Sequence[Hashable],
    load_model: str,
    alpha: float,
    sample_size: int,
    seed: int | None,
) -> TrialResult:
    capacities = {
        node: float(initial_load.get(node, 0.0)) * (1.0 + alpha)
        for node in graph.nodes
    }

    current = graph.copy()
    failed_by_step: list[set[Hashable]] = []
    attacked = [node for node in attacked_nodes if node in current]
    attacked_set = set(attacked)
    current.remove_nodes_from(attacked_set)
    if attacked_set:
        failed_by_step.append(attacked_set)

    step_records: list[dict[str, object]] = []
    cumulative_failed_count = len(attacked_set)
    step_records.append(
        _make_step_record(
            scenario=scenario,
            trial_index=trial_index,
            cascade_step=0,
            current_graph=current,
            loads=initial_load,
            capacities=capacities,
            newly_failed_nodes=attacked,
            cumulative_failed_count=cumulative_failed_count,
        )
    )

    def recompute_load(current_graph: nx.Graph) -> dict[Hashable, float]:
        return compute_node_load(
            current_graph,
            model=load_model,
            sample_size=sample_size,
            seed=seed,
        )

    cascade_step = 0
    while True:
        loads = recompute_load(current)
        overloaded = {
            node
            for node in current.nodes
            if float(loads.get(node, 0.0)) > capacities.get(node, 0.0)
        }
        if not overloaded:
            break
        cascade_step += 1
        current.remove_nodes_from(overloaded)
        failed_by_step.append(overloaded)
        cumulative_failed_count += len(overloaded)
        step_records.append(
            _make_step_record(
                scenario=scenario,
                trial_index=trial_index,
                cascade_step=cascade_step,
                current_graph=current,
                loads=loads,
                capacities=capacities,
                newly_failed_nodes=sorted(overloaded, key=repr),
                cumulative_failed_count=cumulative_failed_count,
            )
        )

    cascade_result = CascadeResult(failed_by_step=failed_by_step, surviving_graph=current)
    summary = _initial_trial_summary(
        scenario=scenario,
        trial_index=trial_index,
        graph=graph,
        attack_nodes=attacked,
        alpha=alpha,
        load_model=load_model,
        sample_size=sample_size,
        seed=seed,
        result=cascade_result,
    )
    return TrialResult(
        scenario=scenario,
        trial_index=trial_index,
        attack_nodes=attacked,
        load_model=load_model,
        alpha=alpha,
        sample_size=sample_size,
        seed=seed,
        initial_load=dict(initial_load),
        cascade=cascade_result,
        step_records=step_records,
        summary=summary,
    )


def run_comparison(
    graph: nx.Graph,
    *,
    attack_count: int = 10,
    random_trials: int = 10,
    seed: int | None = 42,
    load_model: str = "betweenness",
    sample_size: int = 64,
    alpha: float = 0.2,
) -> ComparisonResult:
    simple_graph = project_road_graph(graph)
    initial_load = compute_node_load(
        simple_graph,
        model=load_model,
        sample_size=sample_size,
        seed=seed,
    )

    nodes = list(simple_graph.nodes)
    random_trials_results: list[TrialResult] = []
    for trial_index in range(1, max(random_trials, 1) + 1):
        trial_seed = _random_attack_seed(seed, trial_index)
        attacked_nodes = select_random_nodes(nodes, attack_count, seed=trial_seed)
        random_trials_results.append(
            _run_trial(
                graph=simple_graph,
                initial_load=initial_load,
                scenario="random_failure",
                trial_index=trial_index,
                attacked_nodes=attacked_nodes,
                load_model=load_model,
                alpha=alpha,
                sample_size=sample_size,
                seed=seed,
            )
        )

    high_load_nodes = select_high_load_nodes(initial_load, attack_count)
    high_load_trial = _run_trial(
        graph=simple_graph,
        initial_load=initial_load,
        scenario="high_load_failure",
        trial_index=1,
        attacked_nodes=high_load_nodes,
        load_model=load_model,
        alpha=alpha,
        sample_size=sample_size,
        seed=seed,
    )

    random_summary = _aggregate_trials(
        random_trials_results,
        scenario="random_failure",
        parameters={
            "attack_count": attack_count,
            "random_trials": max(random_trials, 1),
            "seed": seed,
            "load_model": load_model,
            "sample_size": sample_size,
            "alpha": alpha,
        },
    )
    high_load_summary = _aggregate_trials(
        [high_load_trial],
        scenario="high_load_failure",
        parameters={
            "attack_count": attack_count,
            "random_trials": 1,
            "seed": seed,
            "load_model": load_model,
            "sample_size": sample_size,
            "alpha": alpha,
        },
    )

    trial_summaries = [trial.summary for trial in random_trials_results] + [high_load_trial.summary]
    step_records = [row for trial in random_trials_results for row in trial.step_records] + high_load_trial.step_records

    return ComparisonResult(
        parameters={
            "attack_count": attack_count,
            "random_trials": max(random_trials, 1),
            "seed": seed,
            "load_model": load_model,
            "sample_size": sample_size,
            "alpha": alpha,
            "initial_nodes": simple_graph.number_of_nodes(),
            "initial_edges": simple_graph.number_of_edges(),
        },
        random_trials=random_trials_results,
        high_load=high_load_trial,
        random_summary=random_summary,
        high_load_summary=high_load_summary,
        trial_summaries=trial_summaries,
        step_records=step_records,
    )


def _aggregate_trials(
    trials: Sequence[TrialResult],
    *,
    scenario: str,
    parameters: Mapping[str, object],
) -> dict[str, object]:
    final_surviving_nodes = [trial.summary["final_surviving_nodes"] for trial in trials]
    final_largest_component_size = [trial.summary["final_largest_component_size"] for trial in trials]
    cascade_steps = [trial.summary["cascade_steps"] for trial in trials]
    failed_count = [trial.summary["failed_count"] for trial in trials]

    attack_nodes = [trial.attack_nodes for trial in trials]
    return {
        "scenario": scenario,
        **dict(parameters),
        "trial_count": len(trials),
        "attack_nodes": attack_nodes if len(trials) > 1 else attack_nodes[0],
        "final_surviving_nodes_mean": _summarize_numeric(final_surviving_nodes)["mean"],
        "final_surviving_nodes_std": _summarize_numeric(final_surviving_nodes)["std"],
        "final_largest_component_size_mean": _summarize_numeric(final_largest_component_size)["mean"],
        "final_largest_component_size_std": _summarize_numeric(final_largest_component_size)["std"],
        "cascade_steps_mean": _summarize_numeric(cascade_steps)["mean"],
        "cascade_steps_std": _summarize_numeric(cascade_steps)["std"],
        "failed_count_mean": _summarize_numeric(failed_count)["mean"],
        "failed_count_std": _summarize_numeric(failed_count)["std"],
        "final_surviving_nodes_min": min(final_surviving_nodes),
        "final_surviving_nodes_max": max(final_surviving_nodes),
    }


def _step_series_for_trial(trial: TrialResult, metric: str) -> dict[int, float]:
    series: dict[int, float] = {}
    for row in trial.step_records:
        value = row.get(metric)
        if isinstance(value, (int, float)):
            series[int(row["cascade_step"])] = float(value)
    return series


def _aggregate_step_series(trials: Sequence[TrialResult], metric: str) -> list[dict[str, object]]:
    if not trials:
        return []

    step_series = [_step_series_for_trial(trial, metric) for trial in trials]
    max_step = max(max(series) for series in step_series)
    rows: list[dict[str, object]] = []

    for step in range(max_step + 1):
        values: list[float] = []
        for series in step_series:
            if step in series:
                value = series[step]
            else:
                past_steps = [past_step for past_step in series if past_step < step]
                if not past_steps:
                    continue
                value = series[max(past_steps)]
            values.append(float(value))

        stats = _summarize_numeric(values)
        rows.append(
            {
                "cascade_step": step,
                f"{metric}_mean": stats["mean"],
                f"{metric}_std": stats["std"],
            }
        )

    return rows


def write_comparison_outputs(
    results: ComparisonResult,
    output_dir: str | Path,
    *,
    plot_metric: str = "remaining_nodes",
    graph_title: str = "Hitachi cascade comparison",
) -> dict[str, Path]:
    from .plotting import plot_cascade_comparison

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = [results.random_summary, results.high_load_summary]
    trial_rows = [trial.summary for trial in results.random_trials] + [results.high_load.summary]
    step_rows = results.step_records

    report = {
        "parameters": results.parameters,
        "summary": summary_rows,
        "trials": trial_rows,
        "steps": step_rows,
    }

    summary_path = output_dir / "cascade_summary.csv"
    trials_path = output_dir / "cascade_trials.csv"
    steps_path = output_dir / "cascade_steps.csv"
    json_path = output_dir / "cascade_results.json"
    png_path = output_dir / "cascade_comparison.png"

    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    pd.DataFrame(trial_rows).to_csv(trials_path, index=False)
    pd.DataFrame(step_rows).to_csv(steps_path, index=False)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    plot_cascade_comparison(results, png_path, metric=plot_metric, title=graph_title)

    return {
        "summary_csv": summary_path,
        "trials_csv": trials_path,
        "steps_csv": steps_path,
        "json": json_path,
        "png": png_path,
    }
