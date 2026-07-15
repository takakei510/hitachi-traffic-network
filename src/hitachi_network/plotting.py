from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import networkx as nx

from .simulation import ComparisonResult


def _step_series(trial, metric: str) -> dict[int, float]:
    series: dict[int, float] = {}
    for row in trial.step_records:
        value = row.get(metric)
        if isinstance(value, (int, float)):
            series[int(row["cascade_step"])] = float(value)
    return series


def _aligned_values(trials, metric: str, step: int) -> list[float]:
    values: list[float] = []
    for trial in trials:
        series = _step_series(trial, metric)
        if step in series:
            values.append(series[step])
            continue
        previous_steps = [candidate for candidate in series if candidate < step]
        if previous_steps:
            values.append(series[max(previous_steps)])
    return values


def _metric_label(metric: str) -> str:
    labels = {
        "remaining_nodes": "Remaining nodes",
        "largest_component_size": "Largest component size",
    }
    return labels.get(metric, metric.replace("_", " ").title())


def plot_cascade_comparison(
    results: ComparisonResult,
    output_path: str | Path,
    *,
    metric: str = "remaining_nodes",
    title: str = "Cascade comparison",
) -> None:
    """Plot the selected cascade metric for random trials and the high-load case."""
    fig, ax = plt.subplots(figsize=(10, 6))

    random_trials = results.random_trials
    high_load_trial = results.high_load
    max_step = max(
        [int(row["cascade_step"]) for row in results.step_records],
        default=0,
    )

    random_means: list[float] = []
    random_stds: list[float] = []
    steps = list(range(max_step + 1))
    for step in steps:
        values = _aligned_values(random_trials, metric, step)
        if not values:
            random_means.append(0.0)
            random_stds.append(0.0)
            continue
        random_means.append(sum(values) / len(values))
        if len(values) > 1:
            random_stds.append(float((sum((value - random_means[-1]) ** 2 for value in values) / (len(values) - 1)) ** 0.5))
        else:
            random_stds.append(0.0)

    high_load_series = _step_series(high_load_trial, metric)
    high_load_values = []
    last_value = None
    for step in steps:
        if step in high_load_series:
            last_value = high_load_series[step]
        if last_value is None:
            last_value = 0.0
        high_load_values.append(last_value)

    ax.plot(steps, random_means, color="#1565c0", linewidth=2.2, label="random_failure mean")
    if any(random_stds):
        lower = [mean_value - std_value for mean_value, std_value in zip(random_means, random_stds)]
        upper = [mean_value + std_value for mean_value, std_value in zip(random_means, random_stds)]
        ax.fill_between(steps, lower, upper, color="#1565c0", alpha=0.15, label="random_failure ±1σ")
    ax.plot(steps, high_load_values, color="#c62828", linewidth=2.2, marker="o", label="high_load_failure")

    ax.set_title(title)
    ax.set_xlabel("Cascade step")
    ax.set_ylabel(_metric_label(metric))
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
