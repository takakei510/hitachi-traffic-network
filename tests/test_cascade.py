from pathlib import Path
import sys

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitachi_network.cascade import run_node_cascade  # noqa: E402
from hitachi_network.simulation import (  # noqa: E402
    _summarize_numeric,
    project_road_graph,
    run_comparison,
    run_scenario,
    select_high_load_nodes,
    select_random_nodes,
    write_comparison_outputs,
)


def test_project_road_graph_collapses_multiedges_and_removes_self_loops() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=1.0)
    graph.add_edge(1, 1, length=1.0)
    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(1, 2, length=5.0)

    simple_graph = project_road_graph(graph)

    assert simple_graph.number_of_edges() == 1
    assert not list(nx.selfloop_edges(simple_graph))
    assert float(simple_graph[1][2]["length"]) == 5.0


def test_capacity_is_based_on_initial_load() -> None:
    graph = nx.Graph()
    graph.add_node(1)

    call_count = 0

    def recompute_load(current_graph: nx.Graph) -> dict[int, float]:
        nonlocal call_count
        call_count += 1
        if current_graph.number_of_nodes() == 1:
            return {1: 1.3}
        return {}

    result = run_node_cascade(
        graph,
        {1: 1.0},
        set(),
        tolerance=0.2,
        recompute_load=recompute_load,
    )

    assert call_count == 2
    assert result.all_failed == {1}


def test_recompute_load_is_called_for_each_cascade_step() -> None:
    graph = nx.path_graph(3)
    loads_seen: list[int] = []

    def recompute_load(current_graph: nx.Graph) -> dict[int, float]:
        loads_seen.append(current_graph.number_of_nodes())
        if current_graph.number_of_nodes() == 3:
            return {0: 0.0, 1: 2.0, 2: 0.0}
        if current_graph.number_of_nodes() == 2:
            return {0: 0.0, 2: 0.0}
        return {}

    result = run_node_cascade(
        graph,
        {0: 1.0, 1: 1.0, 2: 1.0},
        set(),
        tolerance=0.2,
        recompute_load=recompute_load,
    )

    assert loads_seen == [3, 2]
    assert result.all_failed == {1}


def test_capacity_exceeding_nodes_only_fail_next() -> None:
    graph = nx.path_graph(4)

    def recompute_load(current_graph: nx.Graph) -> dict[int, float]:
        if current_graph.number_of_nodes() == 4:
            return {0: 0.0, 1: 2.0, 2: 2.0, 3: 0.2}
        return {node: 0.0 for node in current_graph.nodes}

    result = run_node_cascade(
        graph,
        {node: 1.0 for node in graph.nodes},
        set(),
        tolerance=0.1,
        recompute_load=recompute_load,
    )

    assert result.all_failed == {1, 2}


def test_high_load_selection_orders_by_load() -> None:
    loads = {"a": 1.0, "b": 4.0, "c": 2.0}

    assert select_high_load_nodes(loads, 2) == ["b", "c"]


def test_random_selection_is_reproducible() -> None:
    nodes = [1, 2, 3, 4, 5]

    assert select_random_nodes(nodes, 3, seed=99) == select_random_nodes(nodes, 3, seed=99)


def test_random_comparison_is_seed_reproducible() -> None:
    graph = nx.MultiDiGraph()
    for node in range(6):
        graph.add_node(node, x=float(node), y=float(node))
    for node in range(6):
        graph.add_edge(node, (node + 1) % 6, length=1.0)

    results_a = run_comparison(
        graph,
        attack_count=2,
        random_trials=3,
        seed=42,
        load_model="degree",
        sample_size=4,
        alpha=0.0,
    )
    results_b = run_comparison(
        graph,
        attack_count=2,
        random_trials=3,
        seed=42,
        load_model="degree",
        sample_size=4,
        alpha=0.0,
    )

    assert [trial.attack_nodes for trial in results_a.random_trials] == [trial.attack_nodes for trial in results_b.random_trials]
    assert results_a.high_load.attack_nodes == results_b.high_load.attack_nodes


def test_step_metrics_are_monotonic_and_bounded() -> None:
    graph = nx.MultiDiGraph()
    for node in range(5):
        graph.add_node(node, x=float(node), y=float(node))
    for node in range(5):
        graph.add_edge(node, (node + 1) % 5, length=1.0)

    trial = run_scenario(
        graph,
        name="random_failure",
        attacked_nodes=[0],
        load_model="degree",
        sample_size=4,
        seed=7,
        alpha=0.0,
    )

    remaining_nodes = [row["remaining_nodes"] for row in trial.step_records]
    largest_component_sizes = [row["largest_component_size"] for row in trial.step_records]

    assert remaining_nodes == sorted(remaining_nodes, reverse=True)
    assert all(component_size <= remaining for component_size, remaining in zip(largest_component_sizes, remaining_nodes))


def test_multiple_trial_statistics_are_correct() -> None:
    stats = _summarize_numeric([1.0, 2.0, 3.0])

    assert stats["mean"] == 2.0
    assert round(stats["std"], 6) == 1.0


def test_csv_json_and_png_are_generated(tmp_path: Path) -> None:
    graph = nx.MultiDiGraph()
    for node in range(6):
        graph.add_node(node, x=float(node), y=float(node))
    for node in range(6):
        graph.add_edge(node, (node + 1) % 6, length=1.0)

    results = run_comparison(
        graph,
        attack_count=2,
        random_trials=2,
        seed=11,
        load_model="degree",
        sample_size=4,
        alpha=0.0,
    )
    outputs = write_comparison_outputs(results, tmp_path, plot_metric="largest_component_size")

    assert outputs["summary_csv"].exists()
    assert outputs["trials_csv"].exists()
    assert outputs["steps_csv"].exists()
    assert outputs["json"].exists()
    assert outputs["png"].exists()

    summary = pd.read_csv(outputs["summary_csv"])
    trials = pd.read_csv(outputs["trials_csv"])
    steps = pd.read_csv(outputs["steps_csv"])

    assert {"random_failure", "high_load_failure"} <= set(summary["scenario"])
    assert {"scenario", "trial_index", "attack_nodes", "cascade_steps"} <= set(trials.columns)
    assert {"scenario", "trial_index", "cascade_step", "remaining_nodes", "largest_component_size", "newly_failed_count", "cumulative_failed_count", "newly_failed_nodes", "max_load_ratio"} <= set(steps.columns)
