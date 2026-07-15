from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hitachi_network.io import load_road_graph
from hitachi_network.plotting import plot_graph


def main() -> None:
    graph = load_road_graph(
        ROOT / "data/raw/Hitachinodes.csv",
        ROOT / "data/raw/Hitachiedges.csv",
        mode="directed",
    )
    print(f"nodes: {graph.number_of_nodes():,}")
    print(f"edges: {graph.number_of_edges():,}")
    print(f"weak components: {__import__('networkx').number_weakly_connected_components(graph):,}")
    plot_graph(graph, ROOT / "outputs/hitachi_network.png")
    print("saved: outputs/hitachi_network.png")


if __name__ == "__main__":
    main()
