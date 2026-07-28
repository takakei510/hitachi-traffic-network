import networkx as nx

from hitachi_network.road_cascade import (
    build_length_adjusted_capacities,
    canonical_edge,
    compute_edge_load,
    run_road_capacity_cascade,
)


def make_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1.0)
    graph.add_edge("B", "C", length=1.0)
    graph.add_edge("C", "D", length=1.0)
    graph.add_edge("D", "A", length=1.0)
    graph.add_edge("A", "C", length=0.5)
    return graph


def test_compute_edge_load_returns_canonical_edges():
    graph = make_graph()
    loads = compute_edge_load(graph)
    assert set(loads) == {canonical_edge(graph, u, v) for u, v in graph.edges()}
    assert all(value >= 0.0 for value in loads.values())


def test_capacity_uses_initial_load_alpha_and_relative_length():
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1.0)
    graph.add_edge("B", "C", length=3.0)
    loads = {
        canonical_edge(graph, "A", "B"): 2.0,
        canonical_edge(graph, "B", "C"): 2.0,
    }
    capacities = build_length_adjusted_capacities(graph, loads, alpha=0.5)
    short_edge = canonical_edge(graph, "A", "B")
    long_edge = canonical_edge(graph, "B", "C")
    assert capacities[short_edge] == 1.5
    assert capacities[long_edge] == 4.5


def test_initial_attack_is_step_zero_and_original_graph_is_unchanged():
    graph = make_graph()
    attacked = canonical_edge(graph, "A", "C")
    original_edges = set(graph.edges())
    result = run_road_capacity_cascade(graph, attacked_edges=[attacked], alpha=0.2)
    assert result.failed_by_step[0] == (attacked,)
    assert attacked in result.all_failed_edges
    assert set(graph.edges()) == original_edges
    assert not result.surviving_graph.has_edge(*attacked)


def test_step_records_match_failed_edges():
    graph = make_graph()
    attacked = canonical_edge(graph, "A", "C")
    result = run_road_capacity_cascade(graph, attacked_edges=[attacked], alpha=0.0, max_steps=5)
    assert result.steps[0].step_index == 0
    assert result.steps[0].failed_edges == (attacked,)
    for index, step in enumerate(result.steps):
        assert step.step_index == index
        assert set(step.failed_edges) == set(result.failed_by_step[index])
        assert step.remaining_edges >= 0
