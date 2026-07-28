from __future__ import annotations

from pathlib import Path
import random
import sys
from typing import Hashable

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hitachi_network.geospatial import extract_radius_subgraph, search_places
from hitachi_network.io import load_road_graph
from hitachi_network.road_cascade import (
    EdgeId,
    RoadCascadeResult,
    canonical_edge,
    compute_edge_load,
    run_road_capacity_cascade,
)
from hitachi_network.simulation import project_road_graph


RADIUS_OPTIONS = {"500 m": 500, "1 km": 1000, "2 km": 2000, "3 km": 3000}
RATIO_BINS = [
    ("safe", "余裕あり（0.0–0.4）", "#1565c0", 0.0, 0.4),
    ("moderate", "比較的安全（0.4–0.7）", "#2e7d32", 0.4, 0.7),
    ("high", "負荷上昇（0.7–0.9）", "#f9a825", 0.7, 0.9),
    ("critical", "故障寸前（0.9–1.0）", "#ef6c00", 0.9, 1.0),
    ("over", "容量超過（1.0超）", "#c62828", 1.0, float("inf")),
]


@st.cache_resource(show_spinner=False)
def load_graph() -> nx.Graph:
    graph = load_road_graph(
        ROOT / "data/raw/Hitachinodes.csv",
        ROOT / "data/raw/Hitachiedges.csv",
        mode="directed",
    )
    return project_road_graph(graph)


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def find_places(query: str):
    return search_places(query, limit=8)


def edge_label(graph: nx.Graph, edge: EdgeId) -> str:
    u, v = edge
    data = graph.get_edge_data(u, v, default={})
    length = float(data.get("length", 0.0))
    return f"{u} → {v}（長さ {length:.1f} m）"


def choose_attack_edge(graph: nx.Graph, mode: str, seed: int) -> EdgeId:
    edges = [canonical_edge(graph, u, v) for u, v in graph.edges()]
    if not edges:
        raise ValueError("対象範囲に道路がありません。")
    if mode == "高負荷道路":
        loads = compute_edge_load(graph)
        return max(edges, key=lambda edge: (loads.get(edge, 0.0), repr(edge)))
    if mode == "ランダム道路":
        return random.Random(seed).choice(edges)
    return edges[0]


def _line_trace(graph: nx.Graph, edges: list[EdgeId], *, name: str, color: str, width: float, hover: bool = True) -> go.Scattermapbox:
    lon: list[float | None] = []
    lat: list[float | None] = []
    custom: list[str | None] = []
    for u, v in edges:
        if u not in graph or v not in graph:
            continue
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        label = edge_label(graph, (u, v))
        lon.extend([float(u_data.get("x", 0.0)), float(v_data.get("x", 0.0)), None])
        lat.extend([float(u_data.get("y", 0.0)), float(v_data.get("y", 0.0)), None])
        custom.extend([label, label, None])
    return go.Scattermapbox(
        lon=lon,
        lat=lat,
        mode="lines",
        line=dict(color=color, width=width),
        name=name,
        customdata=custom,
        hovertemplate="%{customdata}<extra></extra>" if hover else None,
        hoverinfo=None if hover else "skip",
    )


def ratio_category(ratio: float) -> str:
    for key, _label, _color, lower, upper in RATIO_BINS:
        if lower <= ratio < upper or (key == "over" and ratio >= 1.0):
            return key
    return "safe"


def build_step_map(graph: nx.Graph, result: RoadCascadeResult, step_index: int, center_lat: float, center_lon: float) -> go.Figure:
    step = result.steps[step_index]
    initial_failed = set(result.failed_by_step[0]) if result.failed_by_step else set()
    current_failed = set(result.failed_by_step[step_index]) if step_index > 0 else set()
    previous_failed: set[EdgeId] = set()
    for failed_edges in result.failed_by_step[1:step_index]:
        previous_failed.update(failed_edges)

    active_edges = [canonical_edge(graph, u, v) for u, v in graph.edges() if canonical_edge(graph, u, v) not in step.cumulative_failed_edges]
    groups: dict[str, list[EdgeId]] = {key: [] for key, *_ in RATIO_BINS}
    for edge in active_edges:
        groups[ratio_category(float(step.load_ratios.get(edge, 0.0)))].append(edge)

    fig = go.Figure()
    for key, label, color, _lower, _upper in RATIO_BINS:
        if groups[key]:
            fig.add_trace(_line_trace(graph, groups[key], name=label, color=color, width=3.0))
    if previous_failed:
        fig.add_trace(_line_trace(graph, sorted(previous_failed, key=repr), name="過去の故障道路", color="#ef9a9a", width=4.5))
    if current_failed:
        fig.add_trace(_line_trace(graph, sorted(current_failed, key=repr), name="このステップで故障", color="#8e0000", width=6.0))
    if initial_failed:
        fig.add_trace(_line_trace(graph, sorted(initial_failed, key=repr), name="初期故障道路", color="#111111", width=7.0))

    fig.update_layout(
        title=f"Road Capacity Cascade：Step {step_index}",
        mapbox=dict(style="open-street-map", center=dict(lat=center_lat, lon=center_lon), zoom=13),
        margin=dict(l=10, r=10, t=55, b=10),
        height=760,
        legend=dict(orientation="h", y=-0.08),
    )
    return fig


def build_edge_table(graph: nx.Graph, result: RoadCascadeResult) -> pd.DataFrame:
    failure_step: dict[EdgeId, int] = {}
    for step_index, edges in enumerate(result.failed_by_step):
        for edge in edges:
            failure_step[edge] = step_index
    rows = []
    for u, v, data in graph.edges(data=True):
        edge = canonical_edge(graph, u, v)
        initial_load = result.initial_loads.get(edge, 0.0)
        capacity = result.capacities.get(edge, 0.0)
        rows.append(
            {
                "始点": u,
                "終点": v,
                "道路長[m]": round(float(data.get("length", 0.0)), 2),
                "初期負荷": initial_load,
                "容量": capacity,
                "初期負荷率": (initial_load / capacity) if capacity > 0 else 0.0,
                "故障Step": failure_step.get(edge),
            }
        )
    return pd.DataFrame(rows)


st.set_page_config(page_title="Road Capacity Cascade", layout="wide")
st.title("道路容量カスケード故障モード")
st.caption("既存の交差点（ノード）故障モデルとは独立した、道路（エッジ）故障モデルです。")
st.info(
    "容量は Cₑ=Lₑ(0)(1+α)[1+w·max(道路長/平均道路長−1, 0)] で定義します。"
    "短い道路でも初期負荷を下回る容量にならず、平均より長い道路だけに追加容量を与えます。"
)

with st.sidebar:
    st.header("Road Capacity設定")
    alpha = st.slider("alpha（基本容量余裕）", 0.0, 1.0, 0.2, 0.05)
    length_weight = st.slider(
        "道路長の影響 w",
        0.0,
        2.0,
        0.5,
        0.1,
        help="平均道路長を超えた分を、容量へどれだけ強く反映するかを指定します。0では道路長補正なしです。",
    )
    seed = st.number_input("seed", min_value=0, value=42, step=1)
    attack_mode = st.radio("初期故障道路の選び方", ["高負荷道路", "ランダム道路", "候補から選択"])

st.caption(
    "alphaを大きくすると全道路が壊れにくくなります。道路長の影響wを大きくすると、平均より長い道路がより壊れにくくなります。"
)

graph = load_graph()
query = st.text_input("場所名", value="日立駅")
if st.button("場所を探す") or "road_places" not in st.session_state:
    with st.spinner("場所を検索しています..."):
        st.session_state.road_places = find_places(query)

places = st.session_state.get("road_places", [])
if not places:
    st.error("検索結果がありません。")
    st.stop()
selected_place = st.selectbox("検索候補", places, format_func=lambda p: p.display_name)
radius_label = st.radio("対象範囲", list(RADIUS_OPTIONS), horizontal=True, index=1)
radius_m = RADIUS_OPTIONS[radius_label]
subgraph = project_road_graph(extract_radius_subgraph(graph, selected_place.lat, selected_place.lon, radius_m))

st.write(f"対象ノード数: **{subgraph.number_of_nodes()}** / 対象道路数: **{subgraph.number_of_edges()}**")
if subgraph.number_of_edges() == 0:
    st.warning("この範囲には道路がありません。範囲を広げてください。")
    st.stop()

initial_edge = choose_attack_edge(subgraph, attack_mode, int(seed))
if attack_mode == "候補から選択":
    initial_edge = st.selectbox(
        "初期故障道路",
        [canonical_edge(subgraph, u, v) for u, v in subgraph.edges()],
        format_func=lambda edge: edge_label(subgraph, edge),
    )
else:
    st.write(f"初期故障道路: **{edge_label(subgraph, initial_edge)}**")

if st.button("Road Capacity Cascadeを実行", type="primary"):
    with st.spinner("エッジ媒介中心性とカスケード故障を計算しています..."):
        st.session_state.road_result = run_road_capacity_cascade(
            subgraph,
            attacked_edges=[initial_edge],
            alpha=alpha,
            length_weight=length_weight,
        )
        st.session_state.road_graph = subgraph
        st.session_state.road_center = (selected_place.lat, selected_place.lon)
        st.session_state.road_parameters = {
            "alpha": alpha,
            "length_weight": length_weight,
        }

result: RoadCascadeResult | None = st.session_state.get("road_result")
result_graph: nx.Graph | None = st.session_state.get("road_graph")
if result is not None and result_graph is not None:
    st.subheader("ステップごとの負荷率ヒートマップ")
    params = st.session_state.get("road_parameters", {})
    st.caption(
        f"実行条件: alpha={params.get('alpha', alpha):.2f}, "
        f"道路長の影響w={params.get('length_weight', length_weight):.2f}"
    )
    max_step = len(result.steps) - 1

    if max_step <= 0:
        step_index = 0
        st.info("カスケード故障は初期故障のみで終了しました。")
    else:
        step_index = st.slider(
            "表示するStep",
            min_value=0,
            max_value=max_step,
            value=0,
        )
    step = result.steps[step_index]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("このStepの新規故障道路", len(step.failed_edges))
    col2.metric("累積故障道路", len(step.cumulative_failed_edges))
    col3.metric("残存道路", step.remaining_edges)
    col4.metric("最大連結成分ノード数", step.largest_component_size)

    finite_ratios = [value for value in step.load_ratios.values() if value != float("inf")]
    st.caption(f"最大負荷率: {max(finite_ratios, default=0.0):.3f} / 容量超過道路数: {sum(value > 1.0 for value in step.load_ratios.values())}")
    center_lat, center_lon = st.session_state.road_center
    st.plotly_chart(build_step_map(result_graph, result, step_index, center_lat, center_lon), width="stretch")

    with st.expander("道路ごとの初期負荷・容量・故障Step"):
        st.dataframe(build_edge_table(result_graph, result), width="stretch", hide_index=True)

    st.warning("このモデルは実交通量・車線数・道路幅を直接使用していません。道路長を容量補正の代理指標として利用した簡易モデルです。")
