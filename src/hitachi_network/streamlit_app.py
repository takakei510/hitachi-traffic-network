from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from math import asin, atan2, cos, degrees, radians, sin
import os
from pathlib import Path
import sys
import time
from typing import Hashable

import matplotlib
matplotlib.use("Agg")
from matplotlib.collections import LineCollection
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hitachi_network.geospatial import (
    PlaceCandidate,
    build_google_maps_url,
    extract_radius_subgraph,
    node_label_with_location,
    search_places,
)
from hitachi_network.io import load_road_graph
from hitachi_network.plotting import configure_japanese_font
from hitachi_network.simulation import compute_node_load, project_road_graph, run_scenario, select_high_load_nodes, select_random_nodes


STATUS_COLORS = {
    "normal": "#9e9e9e",
    "largest_component": "#1976d2",
    "cascade_failure": "#ef9a9a",
    "current_step_failure": "#c62828",
    "initial_failure": "#111111",
}

STATUS_LABELS = {
    "normal": "正常ノード",
    "largest_component": "最大連結成分",
    "cascade_failure": "過去の連鎖故障ノード",
    "current_step_failure": "このステップで新たに故障",
    "initial_failure": "初期故障ノード",
}

RADIUS_OPTIONS_M = [500, 1000, 2000, 3000]
RADIUS_LABELS = {
    500: "500 m",
    1000: "1 km",
    2000: "2 km",
    3000: "3 km",
}
SCOPE_OPTIONS = ["部分グラフ", "全体グラフ"]
RESULT_EDGE_LIMIT = 5000
RESULT_NORMAL_PREVIEW_LIMIT = 200
RESULT_TABLE_LIMIT = 200
RESULT_DISPLAY_STAGE = int(os.getenv("RESULT_DISPLAY_STAGE", "3"))


configure_japanese_font()


FailureRow = tuple[Hashable, float, float, str, str]
EdgeRow = tuple[float, float, float, float]


@dataclass(frozen=True)
class UIState:
    step_index: int
    initial_failure_nodes: set[Hashable]
    current_step_failure_nodes: set[Hashable]
    cascade_failure_nodes: set[Hashable]
    removed_nodes: set[Hashable]
    active_nodes: set[Hashable]
    largest_component_nodes: set[Hashable]


@dataclass(frozen=True)
class ResultDisplayArtifacts:
    failure_frame: pd.DataFrame
    normal_preview_frame: pd.DataFrame
    map_figure: go.Figure
    timing_rows: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ResultBundle:
    failed_by_step: tuple[tuple[Hashable, ...], ...]
    final_failed_nodes: tuple[Hashable, ...]
    metrics: dict[str, float | int]
    failure_rows: tuple[FailureRow, ...]
    png_bytes: bytes
    timings: tuple[tuple[str, float], ...]


def nearest_node_to_point(graph: nx.Graph, x: float, y: float) -> Hashable:
    best_node: Hashable | None = None
    best_distance = float("inf")
    for node, data in graph.nodes(data=True):
        node_x = float(data.get("x", 0.0))
        node_y = float(data.get("y", 0.0))
        distance = (node_x - x) ** 2 + (node_y - y) ** 2
        if distance < best_distance:
            best_distance = distance
            best_node = node
    if best_node is None:
        raise ValueError("graph has no nodes")
    return best_node


def _largest_component_nodes(graph: nx.Graph) -> set[Hashable]:
    if graph.number_of_nodes() == 0:
        return set()
    if graph.is_directed():
        components = nx.weakly_connected_components(graph)
    else:
        components = nx.connected_components(graph)
    return set(max(components, key=len, default=set()))


def build_ui_state(graph: nx.Graph, result, step_index: int) -> UIState:
    failed_by_step = _normalize_failed_by_step(result)
    initial_failure_nodes = set(failed_by_step[0]) if failed_by_step else set()
    current_step_failure_nodes = set(failed_by_step[step_index]) if 0 < step_index < len(failed_by_step) else set()
    cascade_failure_nodes: set[Hashable] = set()
    for failed_nodes in failed_by_step[1:step_index]:
        cascade_failure_nodes |= set(failed_nodes)

    removed_nodes = initial_failure_nodes | cascade_failure_nodes | current_step_failure_nodes
    active_nodes = set(graph.nodes) - removed_nodes
    active_graph = graph.copy()
    active_graph.remove_nodes_from(removed_nodes)
    largest_component_nodes = _largest_component_nodes(active_graph)

    return UIState(
        step_index=step_index,
        initial_failure_nodes=initial_failure_nodes,
        current_step_failure_nodes=current_step_failure_nodes,
        cascade_failure_nodes=cascade_failure_nodes,
        removed_nodes=removed_nodes,
        active_nodes=active_nodes,
        largest_component_nodes=largest_component_nodes,
    )


def classify_node_status(node: Hashable, state: UIState) -> str:
    if node in state.initial_failure_nodes:
        return "initial_failure"
    if node in state.current_step_failure_nodes:
        return "current_step_failure"
    if node in state.cascade_failure_nodes:
        return "cascade_failure"
    if node in state.largest_component_nodes:
        return "largest_component"
    return "normal"


def build_node_status_dataframe(graph: nx.Graph, result, step_index: int) -> pd.DataFrame:
    state = build_ui_state(graph, result, step_index)
    rows: list[dict[str, object]] = []
    for node, data in graph.nodes(data=True):
        status = classify_node_status(node, state)
        lat = float(data.get("y", 0.0))
        lon = float(data.get("x", 0.0))
        rows.append(
            {
                "node_id": node,
                "x": lon,
                "y": lat,
                "lon": lon,
                "lat": lat,
                "status": status,
                "status_label": STATUS_LABELS[status],
                "display_label": node_label_with_location(graph, node),
                "is_initial_failure": node in state.initial_failure_nodes,
                "is_current_step_failure": node in state.current_step_failure_nodes,
                "is_cascade_failure": node in state.cascade_failure_nodes,
                "is_largest_component": node in state.largest_component_nodes,
                "is_active": node in state.active_nodes,
            }
        )
    return pd.DataFrame(rows)


def build_state_metrics(graph: nx.Graph, result, step_index: int) -> dict[str, float | int]:
    state = build_ui_state(graph, result, step_index)
    initial_nodes = graph.number_of_nodes()
    surviving_nodes = len(state.active_nodes)
    largest_component_size = len(state.largest_component_nodes)
    cumulative_failed_count = len(state.removed_nodes)
    new_failed_count = len(state.initial_failure_nodes) if step_index == 0 else len(state.current_step_failure_nodes)
    return {
        "initial_nodes": initial_nodes,
        "final_surviving_nodes": surviving_nodes,
        "cumulative_failed_count": cumulative_failed_count,
        "new_failed_count": new_failed_count,
        "largest_component_size": largest_component_size,
        "largest_component_ratio": (largest_component_size / initial_nodes) if initial_nodes else 0.0,
        "cascade_steps": step_index,
    }


def _edge_coordinates(graph: nx.Graph) -> tuple[list[float | None], list[float | None]]:
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for u, v in graph.edges():
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        edge_x.extend([float(u_data.get("x", 0.0)), float(v_data.get("x", 0.0)), None])
        edge_y.extend([float(u_data.get("y", 0.0)), float(v_data.get("y", 0.0)), None])
    return edge_x, edge_y


def build_network_figure(graph: nx.Graph, node_frame: pd.DataFrame, *, title: str) -> go.Figure:
    simple_graph = project_road_graph(graph)
    edge_x, edge_y = _edge_coordinates(simple_graph)
    fig = go.Figure()

    fig.add_trace(
        go.Scattergl(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(color="#d0d0d0", width=0.5),
            hoverinfo="skip",
            name="道路",
        )
    )

    for status in ["normal", "largest_component", "cascade_failure", "current_step_failure", "initial_failure"]:
        subset = node_frame[node_frame["status"] == status]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scattergl(
                x=subset["x"],
                y=subset["y"],
                mode="markers",
                name=STATUS_LABELS[status],
                marker=dict(
                    color=STATUS_COLORS[status],
                    size=6 if status == "normal" else 9,
                    line=dict(color="#ffffff", width=0.2),
                ),
                customdata=subset[["node_id", "status_label"]],
                hovertemplate="ノード=%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            )
        )

    fig.update_layout(
        title=dict(text=title, x=0.01, y=0.98, xanchor="left", yanchor="top"),
        template="plotly_white",
        hovermode="closest",
        margin=dict(l=10, r=10, t=70, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0),
        xaxis=dict(title="経度", showgrid=False, zeroline=False),
        yaxis=dict(title="緯度", showgrid=False, zeroline=False, scaleanchor="x", scaleratio=1),
    )
    return fig


def _circle_coordinates(center_lat: float, center_lon: float, radius_m: float, *, points: int = 72) -> tuple[list[float], list[float]]:
    earth_radius_m = 6_371_000.0
    latitudes: list[float] = []
    longitudes: list[float] = []
    angular_distance = radius_m / earth_radius_m
    center_lat_rad = radians(center_lat)
    center_lon_rad = radians(center_lon)

    for index in range(points + 1):
        bearing = 2 * 3.141592653589793 * index / points
        point_lat = asin(
            sin(center_lat_rad) * cos(angular_distance)
            + cos(center_lat_rad) * sin(angular_distance) * cos(bearing)
        )
        point_lon = center_lon_rad + atan2(
            sin(bearing) * sin(angular_distance) * cos(center_lat_rad),
            cos(angular_distance) - sin(center_lat_rad) * sin(point_lat),
        )
        latitudes.append(degrees(point_lat))
        longitudes.append(degrees(point_lon))

    return longitudes, latitudes


def _zoom_for_radius(radius_m: float) -> float:
    if radius_m <= 600:
        return 14.0
    if radius_m <= 1200:
        return 13.2
    if radius_m <= 2200:
        return 12.4
    return 11.6


def _build_map_figure(graph: nx.Graph, node_frame: pd.DataFrame, *, center_lat: float, center_lon: float, radius_m: float, title: str) -> go.Figure:
    simple_graph = project_road_graph(graph)
    edge_lon: list[float | None] = []
    edge_lat: list[float | None] = []
    for u, v in simple_graph.edges():
        u_data = simple_graph.nodes[u]
        v_data = simple_graph.nodes[v]
        edge_lon.extend([float(u_data.get("x", 0.0)), float(v_data.get("x", 0.0)), None])
        edge_lat.extend([float(u_data.get("y", 0.0)), float(v_data.get("y", 0.0)), None])

    circle_lon, circle_lat = _circle_coordinates(center_lat, center_lon, radius_m)
    fig = go.Figure()

    if edge_lon:
        fig.add_trace(
            go.Scattermapbox(
                lon=edge_lon,
                lat=edge_lat,
                mode="lines",
                line=dict(color="#c9c9c9", width=1),
                hoverinfo="skip",
                name="道路",
                showlegend=False,
            )
        )

    fig.add_trace(
        go.Scattermapbox(
            lon=circle_lon,
            lat=circle_lat,
            mode="lines",
            line=dict(color="#1976d2", width=2),
            hoverinfo="skip",
            name="範囲",
        )
    )

    fig.add_trace(
        go.Scattermapbox(
            lon=[center_lon],
            lat=[center_lat],
            mode="markers",
            marker=dict(size=16, color="#ff9800", symbol="star"),
            hovertemplate="検索地点<extra></extra>",
            name="検索地点",
        )
    )

    for status in ["normal", "largest_component", "cascade_failure", "current_step_failure", "initial_failure"]:
        subset = node_frame[node_frame["status"] == status]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scattermapbox(
                lon=subset["lon"],
                lat=subset["lat"],
                mode="markers",
                name=STATUS_LABELS[status],
                marker=dict(color=STATUS_COLORS[status], size=5 if status == "normal" else 10, opacity=0.9),
                customdata=subset[["display_label", "status_label", "node_id"]],
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>",
            )
        )

    fig.update_layout(
        title=dict(text=title, x=0.01, y=0.98, xanchor="left", yanchor="top"),
        mapbox=dict(style="open-street-map", center=dict(lat=center_lat, lon=center_lon), zoom=_zoom_for_radius(radius_m)),
        margin=dict(l=10, r=10, t=70, b=70),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0),
        height=760,
    )
    return fig


def _candidate_label(candidate: PlaceCandidate) -> str:
    primary = candidate.display_name.split(",")[0]
    return f"{primary} ({candidate.lat:.5f}, {candidate.lon:.5f})"


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _load_places_cached(query: str) -> list[PlaceCandidate]:
    return search_places(query, limit=8)


def _node_label_options(graph: nx.Graph) -> list[Hashable]:
    return list(graph.nodes)


def build_simulation_cache_key(*, center_lat: float, center_lon: float, radius_m: int, alpha: float, load_model: str, sample_size: int, seed: int, selected_node: Hashable | None, scope_mode: str) -> tuple[object, ...]:
    return (round(center_lat, 7), round(center_lon, 7), radius_m, alpha, load_model, sample_size, seed, selected_node, scope_mode)


def get_or_build_cached_value(cache: dict[tuple[object, ...], object], key: tuple[object, ...], builder):
    if key not in cache:
        cache[key] = builder()
    return cache[key]


def resolve_active_bundle(cache: dict[tuple[object, ...], dict[str, object]], signature: tuple[object, ...] | None):
    if signature is None:
        return None
    return cache.get(signature)


@st.cache_resource(show_spinner=False)
def _load_cached_graph(nodes_path: Path, edges_path: Path) -> nx.Graph:
    return load_road_graph(nodes_path, edges_path)


@st.cache_data(show_spinner=False)
def _load_places_cached(query: str) -> list[PlaceCandidate]:
    return search_places(query)


def _get_selected_node(graph: nx.Graph, selected_mode: str, load_model: str, sample_size: int, seed: int) -> tuple[Hashable | None, float]:
    if graph.number_of_nodes() == 0:
        return None, 0.0
    if selected_mode == "ランダム故障":
        return select_random_nodes(graph, 1, seed=seed)[0], 0.0
    start = time.perf_counter()
    loads = compute_node_load(graph, model=load_model, sample_size=sample_size, seed=seed)
    elapsed = (time.perf_counter() - start) * 1000.0
    return select_high_load_nodes(loads, 1)[0], elapsed


def _run_trial(graph: nx.Graph, *, selected_node: Hashable, alpha: float, load_model: str, sample_size: int, seed: int):
    return run_scenario(
        graph,
        name="streamlit",
        attacked_nodes=[selected_node],
        alpha=alpha,
        load_model=load_model,
        sample_size=sample_size,
        seed=seed,
    )


def _serialize_graph_for_display(graph: nx.Graph) -> tuple[tuple[tuple[Hashable, float, float, str], ...], tuple[EdgeRow, ...]]:
    node_rows = tuple(
        (
            node,
            float(data.get("x", 0.0)),
            float(data.get("y", 0.0)),
            node_label_with_location(graph, node),
        )
        for node, data in graph.nodes(data=True)
    )
    return node_rows, _build_edge_rows(graph, limit=RESULT_EDGE_LIMIT)


def _build_failure_rows(graph: nx.Graph, result, step_index: int, *, limit: int = RESULT_TABLE_LIMIT) -> tuple[FailureRow, ...]:
    failed_by_step = _normalize_failed_by_step(result)
    failed_nodes = set(_failed_nodes_from_steps(failed_by_step, step_index))
    rows: list[FailureRow] = []
    state = build_ui_state(graph, failed_by_step, step_index)
    for node, data in graph.nodes(data=True):
        if node not in failed_nodes:
            continue
        status = classify_node_status(node, state)
        rows.append((node, float(data.get("x", 0.0)), float(data.get("y", 0.0)), status, node_label_with_location(graph, node)))
        if len(rows) >= limit:
            break
    return tuple(rows)


def _build_normal_preview_rows(graph: nx.Graph, result, step_index: int, *, limit: int = RESULT_NORMAL_PREVIEW_LIMIT) -> tuple[FailureRow, ...]:
    state = build_ui_state(graph, result, step_index)
    rows: list[FailureRow] = []
    for node in graph.nodes:
        if node in state.removed_nodes:
            continue
        if len(rows) >= limit:
            break
        data = graph.nodes[node]
        rows.append((node, float(data.get("x", 0.0)), float(data.get("y", 0.0)), "normal", node_label_with_location(graph, node)))
    return tuple(rows)


def _build_edge_rows(graph: nx.Graph, *, limit: int = RESULT_EDGE_LIMIT) -> tuple[EdgeRow, ...]:
    projected = project_road_graph(graph)
    rows: list[EdgeRow] = []
    for index, (u, v) in enumerate(projected.edges()):
        if index >= limit:
            break
        u_data = projected.nodes[u]
        v_data = projected.nodes[v]
        rows.append((float(u_data.get("x", 0.0)), float(u_data.get("y", 0.0)), float(v_data.get("x", 0.0)), float(v_data.get("y", 0.0))))
    return tuple(rows)


@st.cache_data(show_spinner=False)
def _failure_rows_to_dataframe(rows: tuple[FailureRow, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["node_id", "x", "y", "status", "display_label"])
    if frame.empty:
        return frame
    frame["lon"] = frame["x"]
    frame["lat"] = frame["y"]
    frame["status_label"] = frame["status"].map(STATUS_LABELS).fillna(frame["status"])
    return frame


@st.cache_data(show_spinner=False)
def _normal_preview_rows_to_dataframe(rows: tuple[FailureRow, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["node_id", "x", "y", "status", "display_label"])
    if frame.empty:
        return frame
    frame["lon"] = frame["x"]
    frame["lat"] = frame["y"]
    frame["status_label"] = frame["status"].map(STATUS_LABELS).fillna(frame["status"])
    return frame


@st.cache_resource(show_spinner=False)
def _edge_rows_to_figure(edge_rows: tuple[EdgeRow, ...], failure_rows: tuple[FailureRow, ...], normal_rows: tuple[FailureRow, ...], *, center_lat: float, center_lon: float, radius_m: float, title: str, show_normal_nodes: bool) -> go.Figure:
    circle_lon, circle_lat = _circle_coordinates(center_lat, center_lon, radius_m)
    fig = go.Figure()
    if edge_rows:
        edge_lon: list[float | None] = []
        edge_lat: list[float | None] = []
        for x1, y1, x2, y2 in edge_rows:
            edge_lon.extend([x1, x2, None])
            edge_lat.extend([y1, y2, None])
        fig.add_trace(go.Scattermapbox(lon=edge_lon, lat=edge_lat, mode="lines", line=dict(color="#d0d0d0", width=1), hoverinfo="skip", name="道路"))
    fig.add_trace(go.Scattermapbox(lon=circle_lon, lat=circle_lat, mode="lines", line=dict(color="#1976d2", width=2), hoverinfo="skip", name="選択範囲"))
    fig.add_trace(go.Scattermapbox(lon=[center_lon], lat=[center_lat], mode="markers", marker=dict(size=16, color="#ff9800", symbol="star"), hovertemplate="検索地点<extra></extra>", name="検索地点"))
    failure_frame = _failure_rows_to_dataframe(failure_rows)
    for status in ["initial_failure", "cascade_failure", "current_step_failure"]:
        subset = failure_frame[failure_frame["status"] == status]
        if subset.empty:
            continue
        fig.add_trace(go.Scattermapbox(lon=subset["lon"], lat=subset["lat"], mode="markers", name=STATUS_LABELS[status], marker=dict(color=STATUS_COLORS[status], size=10, opacity=0.95), customdata=subset[["display_label", "status_label", "node_id"]], hovertemplate="%{customdata[0]}<br>%{customdata[1]}<extra></extra>"))
    if show_normal_nodes and normal_rows:
        normal_frame = _normal_preview_rows_to_dataframe(normal_rows)
        if not normal_frame.empty:
            fig.add_trace(go.Scattermapbox(lon=normal_frame["lon"], lat=normal_frame["lat"], mode="markers", name="正常ノード", marker=dict(color=STATUS_COLORS["normal"], size=3, opacity=0.25), hoverinfo="skip"))
    fig.update_layout(title=title, mapbox=dict(style="open-street-map", center=dict(lat=center_lat, lon=center_lon), zoom=_zoom_for_radius(radius_m)), margin=dict(l=0, r=0, t=40, b=0), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0), height=760)
    return fig


def build_failure_dataframe(failure_rows: tuple[FailureRow, ...]) -> pd.DataFrame:
    return _failure_rows_to_dataframe(failure_rows)


def build_result_png_bytes(node_rows: tuple[tuple[Hashable, float, float, str], ...], edge_rows: tuple[EdgeRow, ...], failed_by_step: tuple[tuple[Hashable, ...], ...], step_index: int, *, center_lat: float, center_lon: float, radius_m: float, title: str, edge_limit: int) -> bytes:
    return _build_result_png_cached(node_rows, edge_rows, failed_by_step, step_index, center_lat, center_lon, radius_m, title, edge_limit)


def _build_result_display_artifacts(graph: nx.Graph, result, step_index: int, *, center_lat: float, center_lon: float, radius_m: float, title: str, show_normal_nodes: bool) -> tuple[ResultDisplayArtifacts, list[tuple[str, float]]]:
    timings: list[tuple[str, float]] = []
    start = time.perf_counter()
    failure_rows = _build_failure_rows(graph, result, step_index)
    timings.append(("結果状態DataFrame作成", (time.perf_counter() - start) * 1000.0))
    start = time.perf_counter()
    normal_rows = _build_normal_preview_rows(graph, result, step_index) if show_normal_nodes else tuple()
    timings.append(("結果表表示直前まで", (time.perf_counter() - start) * 1000.0))
    start = time.perf_counter()
    edge_rows = _build_edge_rows(graph, limit=RESULT_EDGE_LIMIT)
    map_figure = _edge_rows_to_figure(edge_rows, failure_rows, normal_rows, center_lat=center_lat, center_lon=center_lon, radius_m=radius_m, title=title, show_normal_nodes=show_normal_nodes)
    timings.append(("結果地図Figure作成", (time.perf_counter() - start) * 1000.0))
    return ResultDisplayArtifacts(failure_frame=_failure_rows_to_dataframe(failure_rows), normal_preview_frame=_normal_preview_rows_to_dataframe(normal_rows), map_figure=map_figure, timing_rows=tuple(timings)), timings


def _timing_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["処理", "時間 (ms)"])
    if frame.empty:
        return frame
    return frame.sort_values("時間 (ms)", ascending=False).reset_index(drop=True)


def _normalize_failed_by_step(source) -> tuple[tuple[Hashable, ...], ...]:
    if source is None:
        return tuple()
    if isinstance(source, dict) and "failed_by_step" in source:
        steps = source["failed_by_step"]
    elif isinstance(source, tuple) and source and all(isinstance(step, (tuple, list, set, frozenset)) for step in source):
        steps = source
    else:
        cascade = getattr(source, "cascade", None)
        if cascade is not None and hasattr(cascade, "failed_by_step"):
            steps = cascade.failed_by_step
        elif hasattr(source, "failed_by_step"):
            steps = source.failed_by_step
        else:
            return tuple()
    return tuple(tuple(step) for step in steps)


def _failed_nodes_from_steps(failed_by_step: tuple[tuple[Hashable, ...], ...], step_index: int) -> tuple[Hashable, ...]:
    failed_nodes: list[Hashable] = []
    for step in failed_by_step[: step_index + 1]:
        for node in step:
            if node not in failed_nodes:
                failed_nodes.append(node)
    return tuple(failed_nodes)


def _result_signature_text(signature: tuple[object, ...]) -> str:
    return "|".join(map(str, signature))


@st.cache_data(show_spinner=False)
def _build_failure_rows_cached(node_rows: tuple[tuple[Hashable, float, float, str], ...], failed_by_step: tuple[tuple[Hashable, ...], ...], step_index: int, limit: int) -> tuple[FailureRow, ...]:
    state_initial = set(failed_by_step[0]) if failed_by_step else set()
    state_current = set(failed_by_step[step_index]) if 0 < step_index < len(failed_by_step) else set()
    state_previous = set(_failed_nodes_from_steps(failed_by_step, max(step_index - 1, 0))) - state_initial
    failed_nodes = state_initial | state_previous | state_current
    rows: list[FailureRow] = []
    for node_id, lon, lat, label in node_rows:
        if node_id not in failed_nodes:
            continue
        if node_id in state_initial:
            status = "initial_failure"
        elif node_id in state_current:
            status = "current_step_failure"
        else:
            status = "cascade_failure"
        rows.append((node_id, lon, lat, status, label))
        if len(rows) >= limit:
            break
    return tuple(rows)


@st.cache_data(show_spinner=False)
def _build_failure_table_cached(failure_rows: tuple[FailureRow, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(failure_rows, columns=["node_id", "lon", "lat", "status", "display_label"])
    if frame.empty:
        return frame
    frame["status_label"] = frame["status"].map(STATUS_LABELS).fillna(frame["status"])
    return frame


@st.cache_data(show_spinner=False)
def _build_result_png_cached(node_rows: tuple[tuple[Hashable, float, float, str], ...], edge_rows: tuple[EdgeRow, ...], failed_by_step: tuple[tuple[Hashable, ...], ...], step_index: int, center_lat: float, center_lon: float, radius_m: float, title: str, edge_limit: int) -> bytes:
    configure_japanese_font()
    fig, ax = plt.subplots(figsize=(10, 10), dpi=160)
    lines: list[list[tuple[float, float]]] = [[(x1, y1), (x2, y2)] for x1, y1, x2, y2 in edge_rows[:edge_limit]]
    if lines:
        ax.add_collection(LineCollection(lines, colors="#d0d0d0", linewidths=0.3, alpha=0.6, zorder=1))
    circle_lon, circle_lat = _circle_coordinates(center_lat, center_lon, radius_m)
    ax.plot(circle_lon, circle_lat, color="#1976d2", linewidth=1.2, zorder=2)
    ax.scatter([center_lon], [center_lat], s=90, c="#ff9800", marker="*", zorder=4, label="検索中心")
    initial_failed = set(failed_by_step[0]) if failed_by_step else set()
    current_failed = set(failed_by_step[step_index]) if 0 < step_index < len(failed_by_step) else set()
    previous_failed = set(_failed_nodes_from_steps(failed_by_step, max(step_index - 1, 0))) - initial_failed
    node_lookup = {node_id: (lon, lat) for node_id, lon, lat, _label in node_rows}
    def _scatter_failed(nodes: set[Hashable], color: str, label: str) -> None:
        if not nodes:
            return
        xs = [node_lookup[node][0] for node in nodes if node in node_lookup]
        ys = [node_lookup[node][1] for node in nodes if node in node_lookup]
        if xs:
            ax.scatter(xs, ys, s=20, c=color, alpha=0.95, zorder=5, label=label)
    _scatter_failed(initial_failed, "#111111", "初期故障")
    _scatter_failed(previous_failed, "#ef9a9a", "過去の連鎖故障")
    _scatter_failed(current_failed, "#c62828", "このステップで新たに故障")
    ax.set_title(title)
    ax.set_xlabel("経度")
    ax.set_ylabel("緯度")
    ax.set_aspect("equal", adjustable="box")
    ax.grid(False)
    ax.legend(loc="upper right")
    fig.tight_layout()
    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()


def build_selected_node_label(node_id, graph) -> str:
    if node_id is None:
        return "未選択"
    attrs = graph.nodes.get(node_id, {})
    lat = attrs.get("y")
    lon = attrs.get("x")
    if lat is not None and lon is not None:
        return f"ノード {node_id}（緯度 {lat:.5f}, 経度 {lon:.5f}）"
    return f"ノード {node_id}"


def main() -> None:
    st.set_page_config(page_title="Hitachi Traffic Network", layout="wide")
    st.title("日立市道路ネットワーク カスケード故障シミュレーション")
    st.caption("展示用の簡易可視化です。実交通流を厳密に再現するものではなく、複雑ネットワークのカスケード故障モデルとして表示します。")
    root = Path(__file__).resolve().parents[2]
    road_load_start = time.perf_counter()
    graph = _load_cached_graph(root / "data/raw/Hitachinodes.csv", root / "data/raw/Hitachiedges.csv")
    st.session_state.last_road_data_load_ms = (time.perf_counter() - road_load_start) * 1000.0
    if "place_query" not in st.session_state:
        st.session_state.place_query = "日立駅"
    if "place_candidates" not in st.session_state:
        st.session_state.place_candidates = _load_places_cached(st.session_state.place_query)
    if "selected_place_index" not in st.session_state:
        st.session_state.selected_place_index = 0
    if "selected_node" not in st.session_state:
        st.session_state.selected_node = next(iter(graph.nodes), None)
    if "active_result_signature" not in st.session_state:
        st.session_state.active_result_signature = None
    if "simulation_cache" not in st.session_state:
        st.session_state.simulation_cache = {}
    if "display_cache" not in st.session_state:
        st.session_state.display_cache = {}
    if "run_id" not in st.session_state:
        st.session_state.run_id = 0
    if "selected_result_step" not in st.session_state:
        st.session_state.selected_result_step = 0
    with st.sidebar:
        st.header("シミュレーション設定")
        alpha = st.slider("alpha", min_value=0.0, max_value=1.0, value=0.2, step=0.05)
        load_model = st.selectbox("load_model", ["betweenness", "degree"], index=0)
        sample_size = st.selectbox("sample_size", [8, 32, 100], index=0)
        seed = st.number_input("seed", min_value=0, value=42, step=1)
        show_normal_nodes = False
    st.subheader("1. 場所を探す")
    with st.form("place-search-form"):
        search_query = st.text_input("場所名", value=st.session_state.place_query, placeholder="日立駅")
        search_submit = st.form_submit_button("場所を探す")
    if search_submit or not st.session_state.place_candidates:
        if not search_query.strip():
            st.error("検索語を入力してください。")
            st.session_state.place_candidates = []
        else:
            st.session_state.place_query = search_query.strip()
            with st.spinner("OpenStreetMap Nominatim で検索しています..."):
                try:
                    st.session_state.place_candidates = _load_places_cached(st.session_state.place_query)
                    st.session_state.selected_place_index = 0
                except Exception as exc:
                    st.error(f"地点検索に失敗しました: {exc}")
                    st.session_state.place_candidates = []
    place_candidates = st.session_state.place_candidates
    if not place_candidates:
        st.error("検索結果がありません。別の場所名を入力してください。")
        st.stop()
    if len(place_candidates) == 1:
        selected_place = place_candidates[0]
        st.success(f"検索結果: {_candidate_label(selected_place)}")
    else:
        selected_place = st.selectbox("候補を選択", place_candidates, index=min(st.session_state.selected_place_index, len(place_candidates) - 1), format_func=_candidate_label)
        st.session_state.selected_place_index = place_candidates.index(selected_place)
    center_lat = selected_place.lat
    center_lon = selected_place.lon
    st.markdown(f"[Googleマップで開く]({build_google_maps_url(center_lat, center_lon)})")
    st.caption(f"検索地点: {selected_place.display_name}")
    st.subheader("2. 範囲を選ぶ")
    radius_m = st.radio("半径", RADIUS_OPTIONS_M, index=0, horizontal=True, format_func=lambda value: RADIUS_LABELS[value])
    scope_mode = st.radio("シミュレーション範囲", SCOPE_OPTIONS, index=0, horizontal=True)
    partial_extract_start = time.perf_counter()
    display_graph = graph if scope_mode == "全体グラフ" else extract_radius_subgraph(graph, center_lat, center_lon, float(radius_m))
    partial_extract_ms = (time.perf_counter() - partial_extract_start) * 1000.0
    simulation_graph = project_road_graph(display_graph)
    if scope_mode == "部分グラフ":
        st.info(f"現在は検索地点を中心にした {RADIUS_LABELS[radius_m]} の部分グラフでシミュレーションします。")
    else:
        st.info("現在は全体グラフでシミュレーションします。")
    if simulation_graph.number_of_nodes() == 0:
        st.error("半径内にノードがありません。別の場所を選ぶか、半径を広げてください。")
        st.stop()
    if simulation_graph.number_of_nodes() < 2 or simulation_graph.number_of_edges() < 1:
        st.warning("ネットワークが小さすぎるため、シミュレーションには十分な接続がありません。")
    st.subheader("3. 故障地点を選ぶ")
    node_options = _node_label_options(simulation_graph)
    if st.session_state.selected_node not in node_options and node_options:
        st.session_state.selected_node = node_options[0]
    preview_frame = pd.DataFrame({"node_id": node_options, "x": [float(simulation_graph.nodes[n].get("x", 0.0)) for n in node_options], "y": [float(simulation_graph.nodes[n].get("y", 0.0)) for n in node_options], "lon": [float(simulation_graph.nodes[n].get("x", 0.0)) for n in node_options], "lat": [float(simulation_graph.nodes[n].get("y", 0.0)) for n in node_options], "status": ["normal"] * len(node_options), "status_label": [STATUS_LABELS["normal"]] * len(node_options), "display_label": [node_label_with_location(simulation_graph, node) for node in node_options]})
    preview_fig = _build_map_figure(simulation_graph, preview_frame, center_lat=center_lat, center_lon=center_lon, radius_m=float(radius_m), title="道路ネットワーク")
    selected_mode = st.radio("故障地点の選び方", ["候補ノード選択", "ランダム故障", "高負荷ノード故障"], index=0)
    initial_load_ms = 0.0
    if selected_mode == "候補ノード選択":
        st.session_state.selected_node = st.selectbox("故障候補ノード", node_options, index=node_options.index(st.session_state.selected_node) if st.session_state.selected_node in node_options else 0, format_func=lambda node: build_selected_node_label(node, simulation_graph))
        st.plotly_chart(preview_fig, width="stretch")
    else:
        selected_node, initial_load_ms = _get_selected_node(simulation_graph, selected_mode, load_model, int(sample_size), int(seed))
        if st.session_state.get("selected_node") != selected_node:
            st.session_state.selected_node = selected_node
        if st.session_state.selected_node is not None:
            st.info(f"自動選択ノード: {build_selected_node_label(st.session_state.selected_node, simulation_graph)}")
        st.plotly_chart(preview_fig, width="stretch")
    st.subheader("4. シミュレーションを実行")
    current_signature = build_simulation_cache_key(center_lat=selected_place.lat, center_lon=selected_place.lon, radius_m=int(radius_m), alpha=float(alpha), load_model=load_model, sample_size=int(sample_size), seed=int(seed), selected_node=st.session_state.selected_node, scope_mode=scope_mode)
    run_disabled = st.session_state.selected_node is None or simulation_graph.number_of_nodes() < 2 or simulation_graph.number_of_edges() < 1
    simulation_cache: dict[tuple[object, ...], dict[str, object]] = st.session_state.simulation_cache
    display_cache: dict[tuple[object, ...], dict[str, object]] = st.session_state.display_cache
    with st.form("simulation-submit-form"):
        st.write(f"run_id: {st.session_state.run_id}")
        st.write(f"現在の故障地点: {build_selected_node_label(st.session_state.selected_node, simulation_graph) if st.session_state.selected_node is not None else '未選択'}")
        st.write(f"現在の半径: {RADIUS_LABELS[radius_m]}")
        simulation_submit = st.form_submit_button("シミュレーションを実行", disabled=run_disabled)
    if simulation_submit:
        st.session_state.run_id += 1
        run_id = st.session_state.run_id
        st.write(f"run_id: {run_id}")
        with st.spinner("カスケード故障を計算しています..."):
            try:
                if current_signature not in simulation_cache:
                    base_timings: list[tuple[str, float]] = [("道路データ読み込み", st.session_state.last_road_data_load_ms), ("部分グラフ抽出", partial_extract_ms if scope_mode == "部分グラフ" else 0.0), ("初期負荷計算", initial_load_ms)]
                    execution_center_lat = float(selected_place.lat)
                    execution_center_lon = float(selected_place.lon)
                    execution_radius_m = float(radius_m)
                    cascade_start = time.perf_counter()
                    trial_result = _run_trial(simulation_graph, selected_node=st.session_state.selected_node, alpha=float(alpha), load_model=load_model, sample_size=int(sample_size), seed=int(seed))
                    base_timings.append(("カスケード計算", (time.perf_counter() - cascade_start) * 1000.0))
                    failed_by_step = _normalize_failed_by_step(trial_result)
                    final_step_index = max(len(failed_by_step) - 1, 0)
                    final_failed_nodes = _failed_nodes_from_steps(failed_by_step, final_step_index)
                    metrics = build_state_metrics(simulation_graph, failed_by_step, final_step_index)
                    node_rows, edge_rows = _serialize_graph_for_display(simulation_graph)
                    result_state_start = time.perf_counter()
                    failure_rows = _build_failure_rows_cached(node_rows, failed_by_step, final_step_index, RESULT_TABLE_LIMIT)
                    result_state_ms = (time.perf_counter() - result_state_start) * 1000.0
                    map_start = time.perf_counter()
                    png_bytes = _build_result_png_cached(node_rows, edge_rows, failed_by_step, final_step_index, execution_center_lat, execution_center_lon, execution_radius_m, f"カスケード故障結果 - ステップ{final_step_index}", RESULT_EDGE_LIMIT)
                    map_ms = (time.perf_counter() - map_start) * 1000.0
                    table_start = time.perf_counter()
                    _build_failure_table_cached(failure_rows)
                    table_ms = (time.perf_counter() - table_start) * 1000.0
                    simulation_cache[current_signature] = {"failed_by_step": failed_by_step, "final_failed_nodes": final_failed_nodes, "metrics": metrics, "node_rows": node_rows, "edge_rows": edge_rows, "center_lat": execution_center_lat, "center_lon": execution_center_lon, "radius_m": execution_radius_m, "step_index": final_step_index, "png_bytes": png_bytes, "failure_rows": failure_rows, "timings": tuple(base_timings + [("結果状態DataFrame作成", result_state_ms), ("結果地図Figure作成", map_ms), ("結果表表示直前まで", table_ms)]), "run_id": run_id}
                st.session_state.active_result_signature = current_signature
                st.session_state.selected_result_step = 0
            except Exception as exc:
                st.error(f"シミュレーションに失敗しました: {exc}")
                st.session_state.active_result_signature = None
    active_signature = st.session_state.active_result_signature
    bundle = resolve_active_bundle(simulation_cache, active_signature)
    if bundle is None:
        return
    failed_by_step = bundle["failed_by_step"]
    final_step_index = max(len(failed_by_step) - 1, 0)
    st.subheader("5. カスケードの進行を確認")
    st.caption("ステップ0は初期故障です。ステップを進めると、新しく容量超過したノードが濃い赤で表示されます。")
    st.session_state.selected_result_step = min(int(st.session_state.selected_result_step), final_step_index)
    control_left, control_center, control_right = st.columns([1, 4, 1])
    with control_left:
        if st.button("◀ 前のステップ", disabled=st.session_state.selected_result_step <= 0):
            st.session_state.selected_result_step = max(st.session_state.selected_result_step - 1, 0)
    with control_right:
        if st.button("次のステップ ▶", disabled=st.session_state.selected_result_step >= final_step_index):
            st.session_state.selected_result_step = min(st.session_state.selected_result_step + 1, final_step_index)
    with control_center:
        step_index = st.slider("表示するステップ", min_value=0, max_value=final_step_index, value=min(int(st.session_state.selected_result_step), final_step_index), step=1, key="cascade_step_slider")
    st.session_state.selected_result_step = step_index
    display_key = (active_signature, step_index, show_normal_nodes)
    if display_key not in display_cache:
        node_rows = bundle["node_rows"]
        edge_rows = bundle["edge_rows"]
        result_state_start = time.perf_counter()
        failure_rows = _build_failure_rows_cached(node_rows, failed_by_step, step_index, RESULT_TABLE_LIMIT)
        result_state_ms = (time.perf_counter() - result_state_start) * 1000.0
        map_start = time.perf_counter()
        png_bytes = _build_result_png_cached(node_rows, edge_rows, failed_by_step, step_index, float(bundle["center_lat"]), float(bundle["center_lon"]), float(bundle["radius_m"]), f"カスケード故障結果 - ステップ{step_index}", RESULT_EDGE_LIMIT)
        map_ms = (time.perf_counter() - map_start) * 1000.0
        table_start = time.perf_counter()
        _build_failure_table_cached(failure_rows)
        table_ms = (time.perf_counter() - table_start) * 1000.0
        display_cache[display_key] = {
            "failure_rows": failure_rows,
            "png_bytes": png_bytes,
            "timings": tuple(
                bundle["timings"][:-3]
                + (
                    ("結果状態DataFrame作成", result_state_ms),
                    ("結果地図Figure作成", map_ms),
                    ("結果表表示直前まで", table_ms),
                )
            ),
            "step_index": step_index,
        }
    display_bundle = display_cache[display_key]
    metrics = build_state_metrics(simulation_graph, failed_by_step, step_index)
    initial_failed_count = len(failed_by_step[0]) if failed_by_step else 0
    new_failed_count = int(metrics["new_failed_count"])
    cumulative_failed_count = int(metrics["cumulative_failed_count"])
    failure_dataframe = build_failure_dataframe(display_bundle["failure_rows"])
    result_png_bytes = display_bundle["png_bytes"]
    debug_png_path = root / "outputs" / f"debug_result_map_step_{step_index}.png"
    debug_png_path.parent.mkdir(parents=True, exist_ok=True)
    debug_png_path.write_bytes(result_png_bytes)
    timings = list(display_bundle["timings"])

    st.subheader("結果")
    metric_columns = st.columns(5)
    metric_columns[0].metric("表示ステップ", f"{step_index} / {final_step_index}")
    metric_columns[1].metric("このステップの新規故障", new_failed_count)
    metric_columns[2].metric("累積故障", cumulative_failed_count)
    metric_columns[3].metric("残存ノード", metrics["final_surviving_nodes"])
    metric_columns[4].metric("最大連結成分比", f"{metrics['largest_component_ratio']:.3f}")
    st.write(f"run_id: {bundle.get('run_id', st.session_state.run_id)}")
    st.write(f"検索地点: {selected_place.display_name}")
    st.write(f"シミュレーション範囲: {scope_mode}")
    st.write(f"故障地点: {build_selected_node_label(st.session_state.selected_node, simulation_graph) if st.session_state.selected_node is not None else '未選択'}")
    st.write(f"初期ノード数: {metrics['initial_nodes']}")
    st.write(f"残存ノード数: {metrics['final_surviving_nodes']}")
    st.write(f"初期故障数: {initial_failed_count}")
    st.write(f"このステップで新たに故障したノード数: {new_failed_count}")
    st.write(f"累積故障数: {cumulative_failed_count}")
    st.write(f"最大連結成分サイズ: {metrics['largest_component_size']}")
    st.write(f"最大連結成分比: {metrics['largest_component_ratio']:.3f}")
    st.write(f"表示中のカスケードステップ: {metrics['cascade_steps']}")
    with st.expander("性能計測"):
        st.dataframe(_timing_frame(timings), width="stretch", hide_index=True)
    if RESULT_DISPLAY_STAGE >= 2:
        st.subheader("結果地図")
        st.image(str(debug_png_path), width="stretch")
    if RESULT_DISPLAY_STAGE >= 3:
        st.subheader("結果表")
        if failure_dataframe.empty:
            st.info("このステップで表示する故障ノードはありません。")
        else:
            st.dataframe(failure_dataframe.head(RESULT_TABLE_LIMIT), width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
