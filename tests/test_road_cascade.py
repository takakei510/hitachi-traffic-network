import networkx as nx

from hitachi_network.road_cascade import (
    build_length_adjusted_capacities,
    canonical_edge,
    compute_edge_load,
    get_lane_info,
    parse_lane_count,
    run_road_capacity_cascade,
)


def make_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1.0, lanes=2, oneway=False, highway="residential")
    graph.add_edge("B", "C", length=1.0, lanes=None, oneway=False, highway="primary")
    graph.add_edge("C", "D", length=1.0, lanes="3,2", oneway=False, highway="trunk")
    graph.add_edge("D", "A", length=1.0, lanes=1, oneway=True, highway="service")
    graph.add_edge("A", "C", length=0.5, lanes=1, oneway=True, highway="service")
    return graph


def test_compute_edge_load_returns_canonical_edges():
    graph = make_graph()
    loads = compute_edge_load(graph)
    assert set(loads) == {canonical_edge(graph, u, v) for u, v in graph.edges()}
    assert all(value >= 0.0 for value in loads.values())


def test_parse_lane_count_sums_directional_multiple_values():
    assert parse_lane_count("3,2") == 5.0
    assert parse_lane_count("2,4") == 6.0
    assert parse_lane_count("2,1") == 3.0
    assert parse_lane_count([3, 2]) == 5.0
    assert parse_lane_count(None) is None
    assert parse_lane_count(float("nan")) is None


def test_lane_info_applies_bidirectional_correction():
    info = get_lane_info({"lanes": "3,2", "oneway": False, "highway": "trunk"})
    assert info.total_lanes == 5.0
    assert info.effective_lanes == 2.5
    assert info.source == "OSM lanes複数値を合計・双方向補正"


def test_lane_info_keeps_all_lanes_for_oneway():
    info = get_lane_info({"lanes": 3, "oneway": True, "highway": "primary"})
    assert info.total_lanes == 3.0
    assert info.effective_lanes == 3.0
    assert info.is_oneway is True


def test_missing_lanes_are_inferred_from_highway():
    trunk = get_lane_info({"lanes": None, "oneway": False, "highway": "trunk"})
    residential = get_lane_info({"lanes": None, "oneway": False, "highway": "residential"})
    assert trunk.effective_lanes == 2.0
    assert residential.effective_lanes == 1.0
    assert trunk.source == "highwayから推定"


def test_capacity_never_falls_below_base_margin():
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1.0, lanes=1, oneway=True)
    graph.add_edge("B", "C", length=3.0, lanes=1, oneway=True)
    loads = {
        canonical_edge(graph, "A", "B"): 2.0,
        canonical_edge(graph, "B", "C"): 2.0,
    }
    capacities = build_length_adjusted_capacities(
        graph,
        loads,
        alpha=0.5,
        length_weight=0.5,
        lane_weight=0.5,
    )
    short_edge = canonical_edge(graph, "A", "B")
    long_edge = canonical_edge(graph, "B", "C")
    assert capacities[short_edge] == 3.0
    assert capacities[long_edge] == 3.75
    assert capacities[short_edge] >= loads[short_edge] * 1.5
    assert capacities[long_edge] >= loads[long_edge] * 1.5


def test_lane_correction_increases_multi_lane_capacity():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", length=1.0, lanes=1, oneway=True)
    graph.add_edge("B", "C", length=1.0, lanes=3, oneway=True)
    loads = {
        canonical_edge(graph, "A", "B"): 2.0,
        canonical_edge(graph, "B", "C"): 2.0,
    }
    capacities = build_length_adjusted_capacities(
        graph,
        loads,
        alpha=0.0,
        length_weight=0.0,
        lane_weight=0.5,
    )
    assert capacities[canonical_edge(graph, "A", "B")] == 2.0
    assert capacities[canonical_edge(graph, "B", "C")] == 4.0


def test_lane_correction_can_be_disabled():
    graph = nx.DiGraph()
    graph.add_edge("A", "B", length=1.0, lanes=1, oneway=True)
    graph.add_edge("B", "C", length=1.0, lanes=4, oneway=True)
    loads = {edge: 2.0 for edge in [canonical_edge(graph, "A", "B"), canonical_edge(graph, "B", "C")]}
    capacities = build_length_adjusted_capacities(
        graph,
        loads,
        alpha=0.5,
        length_weight=0.0,
        lane_weight=1.0,
        use_lane_correction=False,
    )
    assert set(capacities.values()) == {3.0}


def test_initial_state_has_no_capacity_overload():
    graph = make_graph()
    loads = compute_edge_load(graph)
    capacities = build_length_adjusted_capacities(
        graph,
        loads,
        alpha=0.2,
        length_weight=0.5,
        lane_weight=0.5,
    )
    for edge, load in loads.items():
        capacity = capacities[edge]
        if capacity > 0.0:
            assert load / capacity <= 1.0


def test_length_weight_zero_disables_length_bonus():
    graph = nx.Graph()
    graph.add_edge("A", "B", length=1.0, lanes=1, oneway=True)
    graph.add_edge("B", "C", length=10.0, lanes=1, oneway=True)
    loads = {
        canonical_edge(graph, "A", "B"): 2.0,
        canonical_edge(graph, "B", "C"): 2.0,
    }
    capacities = build_length_adjusted_capacities(
        graph,
        loads,
        alpha=0.5,
        length_weight=0.0,
        lane_weight=0.5,
    )
    assert set(capacities.values()) == {3.0}


def test_initial_attack_is_step_zero_and_original_graph_is_unchanged():
    graph = make_graph()
    attacked = canonical_edge(graph, "A", "C")
    original_edges = set(graph.edges())
    result = run_road_capacity_cascade(
        graph,
        attacked_edges=[attacked],
        alpha=0.2,
        length_weight=0.5,
        lane_weight=0.5,
    )
    assert result.failed_by_step[0] == (attacked,)
    assert attacked in result.all_failed_edges
    assert attacked in result.lane_info
    assert set(graph.edges()) == original_edges
    assert not result.surviving_graph.has_edge(*attacked)


def test_step_records_match_failed_edges():
    graph = make_graph()
    attacked = canonical_edge(graph, "A", "C")
    result = run_road_capacity_cascade(
        graph,
        attacked_edges=[attacked],
        alpha=0.0,
        length_weight=0.5,
        lane_weight=0.5,
        max_steps=5,
    )
    assert result.steps[0].step_index == 0
    assert result.steps[0].failed_edges == (attacked,)
    for index, step in enumerate(result.steps):
        assert step.step_index == index
        assert set(step.failed_edges) == set(result.failed_by_step[index])
        assert step.remaining_edges >= 0
