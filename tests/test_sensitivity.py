from pathlib import Path
import sys

import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hitachi_network.sensitivity as sensitivity  # noqa: E402


def _build_small_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for node in range(5):
        graph.add_node(node, x=float(node), y=float(node))
    graph.add_edge(0, 1, length=1.0)
    graph.add_edge(1, 2, length=1.0)
    graph.add_edge(2, 3, length=1.0)
    return graph


def test_sensitivity_analysis_writes_expected_tables_and_outputs(tmp_path: Path, monkeypatch) -> None:
    graph = _build_small_graph()

    monkeypatch.setattr(sensitivity, "select_random_nodes", lambda nodes, attack_count, seed=None: [4, 0][:attack_count])
    monkeypatch.setattr(sensitivity, "select_high_load_nodes", lambda loads, attack_count: [1, 2][:attack_count])

    result = sensitivity.run_sensitivity_analysis(
        graph,
        alphas=[0.1, 0.2],
        sample_sizes=[8, 32],
        attack_count=2,
        random_trials=2,
        seed=42,
        load_model="degree",
    )

    assert len(result.trial_rows) == 12
    assert set(result.trial_rows["scenario"]) == {"random_failure", "high_load_failure"}
    assert result.trial_rows["zero_initial_load_failed_count"].max() >= 1
    assert result.trial_rows["zero_initial_load_failed_ratio"].between(0.0, 1.0).all()
    assert result.trial_rows["largest_component_ratio"].between(0.0, 1.0).all()
    assert (result.trial_rows["condition_execution_seconds"] > 0).all()

    expected_columns = {
        "alpha",
        "sample_size",
        "scenario",
        "trial",
        "final_surviving_nodes",
        "largest_component_size",
        "largest_component_ratio",
        "cumulative_failed_count",
        "cascade_steps",
        "zero_initial_load_failed_count",
        "zero_initial_load_failed_ratio",
    }
    assert expected_columns <= set(result.trial_rows.columns)

    assert len(result.condition_summary) == 8
    assert {"alpha", "sample_size", "scenario", "largest_component_ratio_mean", "zero_initial_load_failed_ratio_mean"} <= set(result.condition_summary.columns)

    outputs = sensitivity.write_sensitivity_outputs(result, tmp_path)
    assert outputs["trial_csv"].exists()
    assert outputs["summary_csv"].exists()
    assert outputs["json"].exists()
    assert outputs["alpha_png"].exists()
    assert outputs["sample_size_png"].exists()
    assert outputs["zero_load_png"].exists()
    assert outputs["comparison_png"].exists()

    trial_frame = pd.read_csv(outputs["trial_csv"])
    summary_frame = pd.read_csv(outputs["summary_csv"])
    assert len(trial_frame) == 12
    assert len(summary_frame) == 8
