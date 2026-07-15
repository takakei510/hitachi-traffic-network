from pathlib import Path
import sys

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitachi_network.geospatial import (  # noqa: E402
    build_google_maps_url,
    build_search_queries,
    extract_radius_subgraph,
    haversine_distance_m,
    nominatim_result_to_candidate,
    node_label_with_location,
    nodes_within_radius,
)


def _build_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, x=140.632, y=36.595)
    graph.add_node(2, x=140.640, y=36.596)
    graph.add_node(3, x=140.700, y=36.700)
    graph.add_edge(1, 2, name="駅前通り")
    graph.add_edge(2, 3, name="海岸通り")
    return graph


def test_haversine_distance_is_reasonable() -> None:
    distance = haversine_distance_m(36.595, 140.632, 36.596, 140.632)

    assert 100 <= distance <= 120


def test_nodes_within_radius_filters_nodes() -> None:
    graph = _build_graph()

    selected_nodes = nodes_within_radius(graph, 36.595, 140.632, 1000)

    assert selected_nodes == [1, 2]


def test_extract_radius_subgraph_excludes_outside_nodes() -> None:
    graph = _build_graph()

    subgraph = extract_radius_subgraph(graph, 36.595, 140.632, 1000)

    assert set(subgraph.nodes) == {1, 2}
    assert set(subgraph.edges) == {(1, 2)}


def test_nominatim_result_is_converted() -> None:
    candidate = nominatim_result_to_candidate(
        {
            "display_name": "Hitachi Station, Hitachi, Ibaraki, Japan",
            "lat": "36.599",
            "lon": "140.651",
            "importance": 0.7,
            "osm_id": 12345,
            "osm_type": "node",
        },
        query="日立駅",
    )

    assert candidate.display_name.startswith("Hitachi Station")
    assert candidate.lat == 36.599
    assert candidate.lon == 140.651
    assert candidate.query == "日立駅"


def test_google_maps_url_uses_coordinates() -> None:
    url = build_google_maps_url(36.599123, 140.650987)

    assert url == "https://www.google.com/maps/search/?api=1&query=36.599123,140.650987"


def test_query_builder_prefers_augmented_search() -> None:
    queries = build_search_queries("日立駅")

    assert queries[0] == "日立駅 茨城県 日立市"
    assert queries[1] == "日立駅"


def test_node_label_prefers_nearby_names() -> None:
    graph = _build_graph()

    assert "駅前通り" in node_label_with_location(graph, 1)
