from pathlib import Path
import sys

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitachi_network.simulation import (  # noqa: E402
    project_road_graph,
    run_comparison,
    select_high_load_nodes,
)


def test_project_road_graph_collapses_multiedges() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=1.0)
    graph.add_edge(1, 2, length=10.0)
    graph.add_edge(1, 2, length=5.0)

    simple_graph = project_road_graph(graph)

    assert simple_graph.number_of_edges() == 1
    assert float(simple_graph[1][2]["length"]) == 5.0


def test_high_load_selection_orders_by_load() -> None:
    loads = {"a": 1.0, "b": 4.0, "c": 2.0}

    assert select_high_load_nodes(loads, 2) == ["b", "c"]


def test_run_comparison_on_small_graph() -> None:
    graph = nx.MultiDiGraph()
    for node in range(4):
        graph.add_node(node, x=float(node), y=float(node))
    graph.add_edge(0, 1, length=1.0)
    graph.add_edge(1, 2, length=1.0)
    graph.add_edge(2, 3, length=1.0)
    graph.add_edge(3, 0, length=1.0)

    results = run_comparison(
        graph,
        attack_count=1,
        seed=7,
        load_model="degree",
        sample_size=4,
        tolerance=0.0,
    )

    assert {result.name for result in results} == {"random_failure", "high_load_failure"}
    assert all(result.summary["attacked_count"] == 1 for result in results)
    assert all("failed_count" in result.summary for result in results)
