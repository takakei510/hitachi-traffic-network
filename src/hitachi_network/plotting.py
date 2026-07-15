from __future__ import annotations

import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.collections import LineCollection
import networkx as nx
import pandas as pd

from .simulation import ComparisonResult


JAPANESE_FONT_CANDIDATES = ("Yu Gothic", "Meiryo", "MS Gothic")


def configure_japanese_font() -> str:
    available_font_names = {font.name for font in font_manager.fontManager.ttflist}
    selected_font = next((candidate for candidate in JAPANESE_FONT_CANDIDATES if candidate in available_font_names), "DejaVu Sans")

    plt.rcParams["font.family"] = [selected_font]
    plt.rcParams["font.sans-serif"] = [selected_font, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    if selected_font == "DejaVu Sans":
        warnings.warn(
            "日本語フォントが見つからないため DejaVu Sans を使用します。日本語が文字化けする可能性があります。",
            RuntimeWarning,
            stacklevel=2,
        )

    return selected_font


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
    configure_japanese_font()
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
    configure_japanese_font()
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


def _scenario_order(frame: pd.DataFrame) -> list[str]:
    preferred = ["random_failure", "high_load_failure"]
    present = [scenario for scenario in preferred if scenario in set(frame["scenario"])]
    for scenario in frame["scenario"]:
        if scenario not in present:
            present.append(scenario)
    return present


def _metric_panel_label(metric: str) -> str:
    labels = {
        "largest_component_ratio": "Largest component ratio",
        "zero_initial_load_failed_ratio": "Failed nodes with zero initial load",
        "final_surviving_nodes": "Final surviving nodes",
        "largest_component_size": "Largest component size",
    }
    return labels.get(metric, metric.replace("_", " ").title())


def _plot_sensitivity_lines(
    frame: pd.DataFrame,
    x_col: str,
    hue_col: str,
    value_col: str,
    title: str,
    output_path: str | Path,
    *,
    y_label: str,
    scenario_label: str,
) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    configure_japanese_font()

    if frame.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title(title)
        ax.set_axis_off()
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        return

    hues = sorted(frame[hue_col].unique())
    scenarios = _scenario_order(frame)
    fig, axes = plt.subplots(1, len(scenarios), figsize=(6.5 * len(scenarios), 4.8), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]

    for axis, scenario in zip(axes, scenarios):
        subset = frame[frame["scenario"] == scenario].copy()
        for hue_value in hues:
            selected = subset[subset[hue_col] == hue_value].sort_values(x_col)
            if selected.empty:
                continue
            label = f"{hue_col}={hue_value}"
            axis.errorbar(
                selected[x_col],
                selected[f"{value_col}_mean"],
                yerr=selected.get(f"{value_col}_std"),
                marker="o",
                linewidth=2,
                capsize=3,
                label=label,
            )
        axis.set_title(f"{scenario_label}: {scenario}")
        axis.set_xlabel(x_col.replace("_", " ").title())
        axis.grid(True, alpha=0.25)

    axes[0].set_ylabel(y_label)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="upper center", ncol=min(len(labels), 4), frameon=False)
    fig.suptitle(title)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_sensitivity_alpha_ratio(frame: pd.DataFrame, output_path: str | Path) -> None:
    _plot_sensitivity_lines(
        frame,
        x_col="alpha",
        hue_col="sample_size",
        value_col="largest_component_ratio",
        title="Alpha sensitivity of largest component ratio",
        output_path=output_path,
        y_label="Largest component ratio",
        scenario_label="scenario",
    )


def plot_sensitivity_sample_size_ratio(frame: pd.DataFrame, output_path: str | Path) -> None:
    _plot_sensitivity_lines(
        frame,
        x_col="sample_size",
        hue_col="alpha",
        value_col="largest_component_ratio",
        title="Sample size sensitivity of largest component ratio",
        output_path=output_path,
        y_label="Largest component ratio",
        scenario_label="scenario",
    )


def plot_sensitivity_zero_load_ratio(frame: pd.DataFrame, output_path: str | Path) -> None:
    _plot_sensitivity_lines(
        frame,
        x_col="sample_size",
        hue_col="alpha",
        value_col="zero_initial_load_failed_ratio",
        title="Zero-initial-load failure ratio",
        output_path=output_path,
        y_label="Failed nodes with zero initial load / all failed nodes",
        scenario_label="scenario",
    )


def plot_sensitivity_comparison(frame: pd.DataFrame, output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    configure_japanese_font()

    if frame.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.set_title("Random vs high-load comparison")
        ax.set_axis_off()
        fig.savefig(output_path, dpi=220, bbox_inches="tight")
        plt.close(fig)
        return

    agg = frame.groupby("scenario", as_index=False).agg(
        final_surviving_nodes_mean=("final_surviving_nodes_mean", "mean"),
        final_surviving_nodes_std=("final_surviving_nodes_mean", "std"),
        largest_component_ratio_mean=("largest_component_ratio_mean", "mean"),
        largest_component_ratio_std=("largest_component_ratio_mean", "std"),
    )

    scenarios = _scenario_order(frame)
    colors = {"random_failure": "#1565c0", "high_load_failure": "#c62828"}
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
    metrics = [
        ("final_surviving_nodes_mean", "final_surviving_nodes_std", "Final surviving nodes"),
        ("largest_component_ratio_mean", "largest_component_ratio_std", "Largest component ratio"),
    ]

    for axis, (mean_col, std_col, ylabel) in zip(axes, metrics):
        values = [float(agg.loc[agg["scenario"] == scenario, mean_col].iloc[0]) for scenario in scenarios if scenario in set(agg["scenario"])]
        errors = [float(agg.loc[agg["scenario"] == scenario, std_col].iloc[0] if not pd.isna(agg.loc[agg["scenario"] == scenario, std_col].iloc[0]) else 0.0) for scenario in scenarios if scenario in set(agg["scenario"])]
        x_positions = list(range(len(values)))
        bars = axis.bar(
            x_positions,
            values,
            yerr=errors,
            color=[colors.get(scenario, "#455a64") for scenario in scenarios if scenario in set(agg["scenario"])],
            capsize=4,
        )
        axis.set_xticks(x_positions)
        axis.set_xticklabels([scenario.replace("_", " ") for scenario in scenarios if scenario in set(agg["scenario"])])
        axis.set_ylabel(ylabel)
        axis.grid(True, axis="y", alpha=0.25)
        for bar, value in zip(bars, values):
            axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.2f}", ha="center", va="bottom", fontsize=9)

    axes[0].set_title("Final surviving nodes")
    axes[1].set_title("Largest component ratio")
    fig.suptitle("Random failure mean vs high-load failure")
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)
