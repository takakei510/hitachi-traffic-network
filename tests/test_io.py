from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitachi_network.io import load_road_graph


def test_load_graph() -> None:
    graph = load_road_graph(
        ROOT / "data/raw/Hitachinodes.csv",
        ROOT / "data/raw/Hitachiedges.csv",
    )
    assert graph.number_of_nodes() > 10_000
    assert graph.number_of_edges() > 20_000
    node = next(iter(graph.nodes))
    assert "x" in graph.nodes[node]
    assert "y" in graph.nodes[node]
