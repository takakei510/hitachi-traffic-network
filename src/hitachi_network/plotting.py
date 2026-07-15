from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import networkx as nx


def plot_cascade_comparison(results, output_path: str | Path, *, title: str = "Cascade comparison") -> None:
    """Plot how many nodes remain after each cascade step for each scenario."""
    fig, ax = plt.subplots(figsize=(10, 6))

    for result in results:
        steps = [0]
        remaining_nodes = [result.summary["initial_nodes"]]
        cumulative_failed = 0
        for step_index, failed_nodes in enumerate(result.cascade.failed_by_step, start=1):
            cumulative_failed += len(failed_nodes)
            steps.append(step_index)
            remaining_nodes.append(result.summary["initial_nodes"] - cumulative_failed)

        ax.plot(steps, remaining_nodes, marker="o", linewidth=2, label=result.name)

    ax.set_title(title)
    ax.set_xlabel("Cascade step")
    ax.set_ylabel("Remaining nodes")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_graph(
    graph: nx.Graph,
    output_path: str | Path | None = None,
    *,
    title: str = "Hitachi road network",
    edge_width: float = 0.25,
) -> None:
    """Draw a large road network efficiently from node coordinates."""
    positions = {
        node: (float(data["x"]), float(data["y"]))
        for node, data in graph.nodes(data=True)
    }
    segments = [
        [positions[u], positions[v]]
        for u, v in graph.edges()
        if u in positions and v in positions
    ]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.add_collection(LineCollection(segments, linewidths=edge_width, alpha=0.6))
    ax.autoscale()
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    fig.tight_layout()

    if output_path is None:
        plt.show()
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
