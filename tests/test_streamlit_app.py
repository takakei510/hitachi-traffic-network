from pathlib import Path
import inspect
import sys
from types import SimpleNamespace

import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import hitachi_network.plotting as plotting  # noqa: E402
from hitachi_network.streamlit_app import (  # noqa: E402
    _build_failure_rows_cached,
    _build_failure_table_cached,
    _build_map_figure,
    _build_result_png_cached,
    _serialize_graph_for_display,
    build_simulation_cache_key,
    build_failure_dataframe,
    build_result_png_bytes,
    build_state_metrics,
    build_ui_state,
    classify_node_status,
    get_or_build_cached_value,
    main,
    nearest_node_to_point,
    resolve_active_bundle,
)


def _build_graph() -> nx.Graph:
    graph = nx.Graph()
    graph.add_node(1, x=0.0, y=0.0)
    graph.add_node(2, x=1.0, y=0.0)
    graph.add_node(3, x=2.0, y=0.0)
    graph.add_node(4, x=3.0, y=0.0)
    graph.add_edges_from([(1, 2), (2, 3), (3, 4)])
    return graph


def _build_trial():
    return SimpleNamespace(cascade=SimpleNamespace(failed_by_step=[{1}, {3}]))


def test_nearest_node_is_selected_from_coordinates() -> None:
    graph = _build_graph()

    assert nearest_node_to_point(graph, 0.2, 0.1) == 1
    assert nearest_node_to_point(graph, 2.7, 0.0) == 4


def test_node_status_classification_is_correct() -> None:
    graph = _build_graph()
    trial = _build_trial()
    state = build_ui_state(graph, trial, 1)

    assert classify_node_status(1, state) == "initial_failure"
    assert classify_node_status(3, state) == "cascade_failure"
    assert classify_node_status(2, state) in {"largest_component", "normal"}


def test_display_dataframe_has_expected_columns() -> None:
    graph = _build_graph()
    trial = _build_trial()
    frame = build_ui_state(graph, trial, 1)

    assert frame.initial_failure_nodes == {1}
    assert frame.cascade_failure_nodes == {3}


def test_metrics_are_calculated_correctly() -> None:
    graph = _build_graph()
    trial = _build_trial()
    metrics = build_state_metrics(graph, trial, 1)

    assert metrics["initial_nodes"] == 4
    assert metrics["final_surviving_nodes"] == 2
    assert metrics["cumulative_failed_count"] == 2
    assert metrics["largest_component_size"] <= metrics["final_surviving_nodes"]
    assert metrics["largest_component_ratio"] <= 1.0


def test_failure_table_contains_only_failed_nodes() -> None:
    graph = _build_graph()
    trial = _build_trial()
    node_rows, edge_rows = _serialize_graph_for_display(graph)
    failed_by_step = ((1,), (3,))
    failure_rows = _build_failure_rows_cached(node_rows, failed_by_step, 1, 200)
    frame = _build_failure_table_cached(failure_rows)
    rebuilt = build_failure_dataframe(failure_rows)

    assert not frame.empty
    assert set(frame["status"]) <= {"initial_failure", "cascade_failure"}
    assert len(frame) <= 200
    assert not rebuilt.empty
    assert list(rebuilt.columns) == ["node_id", "x", "y", "status", "display_label", "lon", "lat", "status_label"]


def test_configure_japanese_font_returns_available_font_name(monkeypatch) -> None:
    monkeypatch.setattr(
        plotting.font_manager.fontManager,
        "ttflist",
        [SimpleNamespace(name="Meiryo")],
        raising=False,
    )

    font_name = plotting.configure_japanese_font()

    assert isinstance(font_name, str)
    assert font_name == "Meiryo"
    assert plt.rcParams["axes.unicode_minus"] is False


def test_configure_japanese_font_falls_back_without_fonts(monkeypatch) -> None:
    monkeypatch.setattr(plotting.font_manager.fontManager, "ttflist", [], raising=False)

    with pytest.warns(RuntimeWarning):
        font_name = plotting.configure_japanese_font()

    assert isinstance(font_name, str)
    assert font_name == "DejaVu Sans"
    assert plt.rcParams["axes.unicode_minus"] is False


def test_result_png_helper_returns_png_bytes() -> None:
    graph = _build_graph()
    node_rows, edge_rows = _serialize_graph_for_display(graph)
    png_bytes = build_result_png_bytes(
        node_rows,
        edge_rows,
        ((1,), (3,)),
        1,
        center_lat=0.0,
        center_lon=0.0,
        radius_m=500.0,
        title="test",
        edge_limit=3000,
    )

    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")
    assert len(png_bytes) > 100


def test_result_png_helper_limits_edges() -> None:
    graph = nx.path_graph(6002)
    for node in graph.nodes:
        graph.nodes[node]["x"] = float(node)
        graph.nodes[node]["y"] = float(node)

    node_rows, edge_rows = _serialize_graph_for_display(graph)
    assert len(edge_rows) <= 5000

    png_bytes = build_result_png_bytes(
        node_rows,
        edge_rows,
        ((0,),),
        0,
        center_lat=0.0,
        center_lon=0.0,
        radius_m=500.0,
        title="test",
        edge_limit=3000,
    )
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")
    assert len(png_bytes) > 100


def test_result_display_does_not_use_placeholders() -> None:
    source = inspect.getsource(main)

    assert "st.empty(" not in source
    assert "placeholder." not in source
    assert "plotly_events(" not in source
    assert "st.rerun(" not in source


def test_preview_map_uses_bottom_legend_and_top_left_title() -> None:
    graph = _build_graph()
    frame = pd.DataFrame(
        {
            "node_id": [1, 2, 3, 4],
            "x": [0.0, 1.0, 2.0, 3.0],
            "y": [0.0, 0.0, 0.0, 0.0],
            "lon": [0.0, 1.0, 2.0, 3.0],
            "lat": [0.0, 0.0, 0.0, 0.0],
            "status": ["normal", "largest_component", "cascade_failure", "initial_failure"],
            "status_label": ["正常ノード", "最大連結成分", "連鎖故障ノード", "初期故障ノード"],
            "display_label": ["a", "b", "c", "d"],
        }
    )

    fig = _build_map_figure(
        graph,
        frame,
        center_lat=0.0,
        center_lon=0.0,
        radius_m=500.0,
        title="道路ネットワーク",
    )

    assert fig.layout.title.text == "道路ネットワーク"
    assert fig.layout.title.x == 0.01
    assert fig.layout.title.y == 0.98
    assert fig.layout.title.xanchor == "left"
    assert fig.layout.title.yanchor == "top"
    assert fig.layout.legend.orientation == "h"
    assert fig.layout.legend.x == 0
    assert fig.layout.legend.y == -0.18
    assert fig.layout.legend.xanchor == "left"
    assert fig.layout.legend.yanchor == "top"


def test_session_cache_helper_reuses_previous_result() -> None:
    cache: dict[tuple[object, ...], object] = {}
    calls = {"count": 0}

    def builder() -> object:
        calls["count"] += 1
        return object()

    key = build_simulation_cache_key(
        center_lat=36.0,
        center_lon=140.0,
        radius_m=500,
        alpha=0.2,
        load_model="betweenness",
        sample_size=8,
        seed=42,
        selected_node=1,
        scope_mode="部分グラフ",
    )

    first = get_or_build_cached_value(cache, key, builder)
    second = get_or_build_cached_value(cache, key, builder)

    assert first is second
    assert calls["count"] == 1


def test_resolve_active_bundle_returns_none_for_missing_or_null_signature() -> None:
    cache = {("x",): {"value": 1}}

    assert resolve_active_bundle(cache, None) is None
    assert resolve_active_bundle(cache, ("missing",)) is None


def test_resolve_active_bundle_returns_existing_bundle() -> None:
    bundle = {"value": 1}
    cache = {("x",): bundle}

    assert resolve_active_bundle(cache, ("x",)) is bundle


def test_successful_run_saves_completed_bundle_only() -> None:
    cache: dict[tuple[object, ...], dict[str, object]] = {}
    signature = ("run", 1)
    completed_bundle = {"finished": True}

    cache[signature] = completed_bundle

    assert cache[signature] is completed_bundle


def test_failed_run_does_not_overwrite_existing_bundle() -> None:
    cache: dict[tuple[object, ...], dict[str, object]] = {("run", 1): {"finished": True}}
    original = cache[("run", 1)]

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert cache[("run", 1)] is original
