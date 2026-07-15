from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Callable, Iterable, Sequence

import networkx as nx
import pandas as pd

from .simulation import (
    _run_trial,
    compute_node_load,
    project_road_graph,
    select_high_load_nodes,
    select_random_nodes,
)


ZERO_THRESHOLD = 1e-12
SMALL_THRESHOLD = 1e-6


@dataclass(frozen=True)
class SensitivityAnalysisResult:
    trial_rows: pd.DataFrame
    condition_summary: pd.DataFrame
    metadata: dict[str, object]


def _largest_component_size(graph: nx.Graph) -> int:
    if graph.number_of_nodes() == 0:
        return 0
    if graph.is_directed():
        components = nx.weakly_connected_components(graph)
    else:
        components = nx.connected_components(graph)
    return max((len(component) for component in components), default=0)


def _fraction(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _mean_std(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "std": 0.0}
    if len(values) == 1:
        return {"mean": float(values[0]), "std": 0.0}
    return {"mean": float(mean(values)), "std": float(stdev(values))}


def _parse_numeric_list(values: Iterable[float | int | str]) -> list[float]:
    parsed: list[float] = []
    for value in values:
        parsed.append(float(value))
    return parsed


def _prepare_graph(graph: nx.Graph) -> nx.Graph:
    return project_road_graph(graph)


def _build_trial_row(
    *,
    graph: nx.Graph,
    scenario: str,
    trial_index: int,
    alpha: float,
    sample_size: int,
    seed: int | None,
    load_model: str,
    attack_nodes: Sequence[object],
    trial_result,
    initial_zero_load_count: int,
    initial_small_load_count: int,
    initial_zero_capacity_count: int,
    initial_small_capacity_count: int,
    trial_seconds: float,
    condition_seconds: float,
) -> dict[str, object]:
    initial_nodes = graph.number_of_nodes()
    final_surviving_nodes = trial_result.cascade.surviving_graph.number_of_nodes()
    largest_component_size = _largest_component_size(trial_result.cascade.surviving_graph)
    cumulative_failed_count = len(trial_result.cascade.all_failed)
    zero_initial_load_failed_count = sum(
        1
        for node in trial_result.cascade.all_failed
        if float(trial_result.initial_load.get(node, 0.0)) <= ZERO_THRESHOLD
    )

    return {
        "alpha": alpha,
        "sample_size": sample_size,
        "scenario": scenario,
        "trial": trial_index,
        "attack_count": len(attack_nodes),
        "attack_nodes": json.dumps([repr(node) for node in attack_nodes], ensure_ascii=False),
        "seed": seed,
        "load_model": load_model,
        "alpha_capacity": alpha,
        "initial_nodes": initial_nodes,
        "initial_zero_load_count": initial_zero_load_count,
        "initial_small_load_count": initial_small_load_count,
        "initial_zero_capacity_count": initial_zero_capacity_count,
        "initial_small_capacity_count": initial_small_capacity_count,
        "final_surviving_nodes": final_surviving_nodes,
        "largest_component_size": largest_component_size,
        "largest_component_ratio": _fraction(largest_component_size, initial_nodes),
        "cumulative_failed_count": cumulative_failed_count,
        "cascade_steps": max(len(trial_result.cascade.failed_by_step) - 1, 0),
        "zero_initial_load_failed_count": zero_initial_load_failed_count,
        "zero_initial_load_failed_ratio": _fraction(zero_initial_load_failed_count, cumulative_failed_count),
        "trial_execution_seconds": trial_seconds,
        "condition_execution_seconds": condition_seconds,
    }


def _aggregate_condition_rows(trial_rows: pd.DataFrame) -> pd.DataFrame:
    grouped = trial_rows.groupby(["alpha", "sample_size", "scenario"], as_index=False)
    rows: list[dict[str, object]] = []
    for (_, _, scenario), group in grouped:
        summary = {
            "alpha": float(group.iloc[0]["alpha"]),
            "sample_size": int(group.iloc[0]["sample_size"]),
            "scenario": scenario,
            "trial_count": int(len(group)),
            "attack_count": int(group.iloc[0]["attack_count"]),
            "load_model": group.iloc[0]["load_model"],
            "seed": int(group.iloc[0]["seed"]),
            "condition_execution_seconds": float(group.iloc[0]["condition_execution_seconds"]),
            "final_surviving_nodes_mean": float(group["final_surviving_nodes"].mean()),
            "final_surviving_nodes_std": float(group["final_surviving_nodes"].std(ddof=1) if len(group) > 1 else 0.0),
            "largest_component_size_mean": float(group["largest_component_size"].mean()),
            "largest_component_size_std": float(group["largest_component_size"].std(ddof=1) if len(group) > 1 else 0.0),
            "largest_component_ratio_mean": float(group["largest_component_ratio"].mean()),
            "largest_component_ratio_std": float(group["largest_component_ratio"].std(ddof=1) if len(group) > 1 else 0.0),
            "cumulative_failed_count_mean": float(group["cumulative_failed_count"].mean()),
            "cascade_steps_mean": float(group["cascade_steps"].mean()),
            "zero_initial_load_failed_count_mean": float(group["zero_initial_load_failed_count"].mean()),
            "zero_initial_load_failed_ratio_mean": float(group["zero_initial_load_failed_ratio"].mean()),
            "zero_initial_load_failed_ratio_std": float(group["zero_initial_load_failed_ratio"].std(ddof=1) if len(group) > 1 else 0.0),
        }
        rows.append(summary)
    return pd.DataFrame(rows)


def run_sensitivity_analysis(
    graph: nx.Graph,
    *,
    alphas: Sequence[float],
    sample_sizes: Sequence[int],
    attack_count: int = 2,
    random_trials: int = 10,
    seed: int | None = 42,
    load_model: str = "betweenness",
    zero_threshold: float = ZERO_THRESHOLD,
    small_threshold: float = SMALL_THRESHOLD,
    progress: Callable[[str], None] | None = None,
) -> SensitivityAnalysisResult:
    simple_graph = _prepare_graph(graph)
    nodes = list(simple_graph.nodes)
    trial_rows: list[dict[str, object]] = []
    condition_seconds_map: dict[tuple[float, int], float] = {}
    overall_started = time.perf_counter()

    def emit(message: str) -> None:
        if progress is not None:
            progress(message)

    for sample_size in sample_sizes:
        emit(f"[sensitivity] sample_size={sample_size} initial load")
        load_started = time.perf_counter()
        initial_load = compute_node_load(
            simple_graph,
            model=load_model,
            sample_size=sample_size,
            seed=seed,
        )
        load_seconds = time.perf_counter() - load_started
        initial_zero_load_nodes = {node for node, value in initial_load.items() if float(value) <= zero_threshold}
        initial_small_load_nodes = {node for node, value in initial_load.items() if float(value) <= small_threshold}

        attack_nodes_by_trial = {
            trial_index: select_random_nodes(nodes, attack_count, seed=None if seed is None else seed + trial_index)
            for trial_index in range(1, max(random_trials, 1) + 1)
        }
        high_load_attack_nodes = select_high_load_nodes(initial_load, attack_count)

        for alpha in alphas:
            condition_started = time.perf_counter()
            emit(f"[sensitivity] alpha={alpha}, sample_size={sample_size} random trials")
            for trial_index in range(1, max(random_trials, 1) + 1):
                trial_seed = seed
                attack_nodes = attack_nodes_by_trial[trial_index]
                trial_started = time.perf_counter()
                trial_result = _run_trial(
                    graph=simple_graph,
                    initial_load=initial_load,
                    scenario="random_failure",
                    trial_index=trial_index,
                    attacked_nodes=attack_nodes,
                    load_model=load_model,
                    alpha=alpha,
                    sample_size=sample_size,
                    seed=trial_seed,
                )
                trial_seconds = time.perf_counter() - trial_started
                trial_rows.append(
                    _build_trial_row(
                        graph=simple_graph,
                        scenario="random_failure",
                        trial_index=trial_index,
                        alpha=alpha,
                        sample_size=sample_size,
                        seed=seed,
                        load_model=load_model,
                        attack_nodes=attack_nodes,
                        trial_result=trial_result,
                        initial_zero_load_count=len(initial_zero_load_nodes),
                        initial_small_load_count=len(initial_small_load_nodes),
                        initial_zero_capacity_count=len(initial_zero_load_nodes),
                        initial_small_capacity_count=len(initial_small_load_nodes),
                        trial_seconds=trial_seconds,
                        condition_seconds=0.0,
                    )
                )

            emit(f"[sensitivity] alpha={alpha}, sample_size={sample_size} high load trial")
            trial_started = time.perf_counter()
            high_load_result = _run_trial(
                graph=simple_graph,
                initial_load=initial_load,
                scenario="high_load_failure",
                trial_index=1,
                attacked_nodes=high_load_attack_nodes,
                load_model=load_model,
                alpha=alpha,
                sample_size=sample_size,
                seed=seed,
            )
            high_load_seconds = time.perf_counter() - trial_started
            trial_rows.append(
                _build_trial_row(
                    graph=simple_graph,
                    scenario="high_load_failure",
                    trial_index=1,
                    alpha=alpha,
                    sample_size=sample_size,
                    seed=seed,
                    load_model=load_model,
                    attack_nodes=high_load_attack_nodes,
                    trial_result=high_load_result,
                    initial_zero_load_count=len(initial_zero_load_nodes),
                    initial_small_load_count=len(initial_small_load_nodes),
                    initial_zero_capacity_count=len(initial_zero_load_nodes),
                    initial_small_capacity_count=len(initial_small_load_nodes),
                    trial_seconds=high_load_seconds,
                    condition_seconds=0.0,
                )
            )

            condition_seconds = time.perf_counter() - condition_started
            condition_seconds_map[(alpha, sample_size)] = condition_seconds + load_seconds

    trial_df = pd.DataFrame(trial_rows)
    for (alpha, sample_size), seconds in condition_seconds_map.items():
        condition_mask = (trial_df["alpha"] == alpha) & (trial_df["sample_size"] == sample_size)
        trial_df.loc[condition_mask, "condition_execution_seconds"] = seconds

    condition_summary = _aggregate_condition_rows(trial_df)
    metadata = {
        "attack_count": attack_count,
        "random_trials": max(random_trials, 1),
        "seed": seed,
        "load_model": load_model,
        "alphas": list(alphas),
        "sample_sizes": list(sample_sizes),
        "zero_threshold": zero_threshold,
        "small_threshold": small_threshold,
        "initial_nodes": simple_graph.number_of_nodes(),
        "initial_edges": simple_graph.number_of_edges(),
        "total_execution_seconds": time.perf_counter() - overall_started,
    }
    return SensitivityAnalysisResult(
        trial_rows=trial_df,
        condition_summary=condition_summary,
        metadata=metadata,
    )


def write_sensitivity_outputs(
    result: SensitivityAnalysisResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    from .plotting import (
        plot_sensitivity_alpha_ratio,
        plot_sensitivity_comparison,
        plot_sensitivity_sample_size_ratio,
        plot_sensitivity_zero_load_ratio,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trial_csv = output_dir / "sensitivity_results.csv"
    summary_csv = output_dir / "sensitivity_summary.csv"
    json_path = output_dir / "sensitivity_results.json"
    alpha_png = output_dir / "alpha_vs_component_ratio.png"
    sample_size_png = output_dir / "sample_size_vs_component_ratio.png"
    zero_load_png = output_dir / "zero_load_failure_ratio.png"
    comparison_png = output_dir / "random_vs_high_load_comparison.png"

    result.trial_rows.to_csv(trial_csv, index=False)
    result.condition_summary.to_csv(summary_csv, index=False)
    json_path.write_text(
        json.dumps(
            {
                "metadata": result.metadata,
                "trial_rows": result.trial_rows.to_dict(orient="records"),
                "condition_summary": result.condition_summary.to_dict(orient="records"),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    plot_sensitivity_alpha_ratio(result.condition_summary, alpha_png)
    plot_sensitivity_sample_size_ratio(result.condition_summary, sample_size_png)
    plot_sensitivity_zero_load_ratio(result.condition_summary, zero_load_png)
    plot_sensitivity_comparison(result.condition_summary, comparison_png)

    return {
        "trial_csv": trial_csv,
        "summary_csv": summary_csv,
        "json": json_path,
        "alpha_png": alpha_png,
        "sample_size_png": sample_size_png,
        "zero_load_png": zero_load_png,
        "comparison_png": comparison_png,
    }