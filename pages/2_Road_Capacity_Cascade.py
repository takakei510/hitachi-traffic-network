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


RADIUS_OPTIONS = {
    "500 m": 500,
    "1 km": 1000,
    "2 km": 2000,
    "3 km": 3000,
    "5 km": 5000,
}

SAMPLE_OPTIONS = {
    "高速（32ノード）": 32,
    "標準（64ノード）": 64,
    "高精度（128ノード）": 128,
    "厳密計算": None,
}

RATIO_BINS = [
    ("safe", "余裕あり（0.0–0.4）", "#90caf9", 0.0, 0.4),
    ("moderate", "比較的安全（0.4–0.7）", "#4dd0e1", 0.4, 0.7),
    ("high", "負荷上昇（0.7–0.9）", "#fdd835", 0.7, 0.9),
    ("critical", "故障寸前（0.9–1.0）", "#fb8c00", 0.9, 1.0),
    ("over", "容量超過（1.0超）", "#e53935", 1.0, float("inf")),
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
    lanes = data.get("lanes")
    lane_text = "不明" if lanes is None or str(lanes).lower() == "nan" else str(lanes)
    return f"{u} → {v}（長さ {length:.1f} m / lanes={lane_text}）"


def choose_attack_edge(
    graph: nx.Graph,
    mode: str,
    seed: int,
    sample_size: int | None,
) -> EdgeId:
    edges = [canonical_edge(graph, u, v) for u, v in graph.edges()]
    if not edges:
        raise ValueError("対象範囲に道路がありません。")
    if mode == "高負荷道路":
        loads = compute_edge_load(graph, sample_size=sample_size, seed=seed)
        return max(edges, key=lambda edge: (loads.get(edge, 0.0), repr(edge)))
    if mode == "ランダム道路":
        return random.Random(seed).choice(edges)
    return edges[0]


def _map_zoom(radius_m: int) -> float:
    if radius_m <= 500:
        return 14.0
    if radius_m <= 1000:
        return 13.2
    if radius_m <= 2000:
        return 12.4
    if radius_m <= 3000:
        return 11.7
    return 10.9


def _line_trace(
    graph: nx.Graph,
    edges: list[EdgeId],
    *,
    name: str,
    color: str,
    width: float,
    opacity: float = 1.0,
    hover: bool = True,
) -> go.Scattermapbox:
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
        opacity=opacity,
        name=name,
        customdata=custom,
        hovertemplate="%{customdata}<extra></extra>" if hover else None,
        hoverinfo=None if hover else "skip",
    )


def build_attack_selection_map(
    graph: nx.Graph,
    center_lat: float,
    center_lon: float,
    radius_m: int,
    selected_edge: EdgeId | None,
) -> tuple[go.Figure, list[EdgeId]]:
    """Build a map whose road midpoint markers can be selected by Streamlit."""
    edges = [canonical_edge(graph, u, v) for u, v in graph.edges()]
    fig = go.Figure()
    fig.add_trace(
        _line_trace(
            graph,
            edges,
            name="選択可能な道路",
            color="#42a5f5",
            width=1.5,
            opacity=0.72,
            hover=False,
        )
    )

    mid_lons: list[float] = []
    mid_lats: list[float] = []
    labels: list[str] = []
    selectable_edges: list[EdgeId] = []
    for edge in edges:
        u, v = edge
        if u not in graph or v not in graph:
            continue
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        mid_lons.append((float(u_data.get("x", 0.0)) + float(v_data.get("x", 0.0))) / 2.0)
        mid_lats.append((float(u_data.get("y", 0.0)) + float(v_data.get("y", 0.0))) / 2.0)
        labels.append(edge_label(graph, edge))
        selectable_edges.append(edge)

    fig.add_trace(
        go.Scattermapbox(
            lon=mid_lons,
            lat=mid_lats,
            mode="markers",
            marker=dict(size=12, color="rgba(33,150,243,0.10)"),
            name="クリック位置",
            text=labels,
            customdata=list(range(len(selectable_edges))),
            hovertemplate="%{text}<br>クリックして初期故障道路に設定<extra></extra>",
            selected=dict(marker=dict(size=15, color="#111111", opacity=0.9)),
            unselected=dict(marker=dict(opacity=0.10)),
            showlegend=False,
        )
    )

    if selected_edge is not None and graph.has_edge(*selected_edge):
        fig.add_trace(
            _line_trace(
                graph,
                [selected_edge],
                name="選択中の初期故障道路",
                color="#111111",
                width=5.0,
                opacity=1.0,
            )
        )

    fig.update_layout(
        title="初期故障道路を地図から選択",
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=_map_zoom(radius_m),
        ),
        margin=dict(l=10, r=10, t=55, b=10),
        height=620,
        clickmode="event+select",
        showlegend=False,
    )
    return fig, selectable_edges


def ratio_category(ratio: float) -> str:
    for key, _label, _color, lower, upper in RATIO_BINS:
        if lower <= ratio < upper or (key == "over" and ratio >= 1.0):
            return key
    return "safe"


def build_step_map(
    graph: nx.Graph,
    result: RoadCascadeResult,
    step_index: int,
    center_lat: float,
    center_lon: float,
    radius_m: int,
) -> go.Figure:
    step = result.steps[step_index]
    initial_failed = set(result.failed_by_step[0]) if result.failed_by_step else set()
    current_failed = set(result.failed_by_step[step_index]) if step_index > 0 else set()
    previous_failed: set[EdgeId] = set()
    for failed_edges in result.failed_by_step[1:step_index]:
        previous_failed.update(failed_edges)

    cumulative_failed = set(step.cumulative_failed_edges)
    active_edges = [
        canonical_edge(graph, u, v)
        for u, v in graph.edges()
        if canonical_edge(graph, u, v) not in cumulative_failed
    ]

    groups: dict[str, list[EdgeId]] = {key: [] for key, *_ in RATIO_BINS}
    for edge in active_edges:
        groups[ratio_category(float(step.load_ratios.get(edge, 0.0)))].append(edge)

    fig = go.Figure()
    for key, label, color, _lower, _upper in RATIO_BINS:
        if groups[key]:
            width = 2.0 if key in {"critical", "over"} else 1.25
            fig.add_trace(
                _line_trace(
                    graph,
                    groups[key],
                    name=label,
                    color=color,
                    width=width,
                    opacity=0.88,
                )
            )

    if previous_failed:
        fig.add_trace(
            _line_trace(
                graph,
                sorted(previous_failed, key=repr),
                name="過去の故障道路",
                color="#616161",
                width=1.8,
                opacity=0.28,
            )
        )
    if current_failed:
        fig.add_trace(
            _line_trace(
                graph,
                sorted(current_failed, key=repr),
                name="このステップで故障",
                color="#c2185b",
                width=3.2,
                opacity=0.95,
            )
        )
    if initial_failed:
        fig.add_trace(
            _line_trace(
                graph,
                sorted(initial_failed, key=repr),
                name="初期故障道路",
                color="#111111",
                width=4.0,
                opacity=1.0,
            )
        )

    fig.update_layout(
        title=f"Road Capacity Cascade：Step {step_index}",
        mapbox=dict(
            style="open-street-map",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=_map_zoom(radius_m),
        ),
        margin=dict(l=10, r=10, t=60, b=85),
        height=760,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.05,
            xanchor="left",
            x=0,
            bgcolor="rgba(255,255,255,0.85)",
        ),
    )
    return fig


def build_edge_table(graph: nx.Graph, result: RoadCascadeResult) -> pd.DataFrame:
    failure_step: dict[EdgeId, int] = {}
    for step_index, edges in enumerate(result.failed_by_step):
        for edge in edges:
            failure_step[edge] = step_index

    rows: list[dict[str, object]] = []
    for u, v, data in graph.edges(data=True):
        edge = canonical_edge(graph, u, v)
        initial_load = result.initial_loads.get(edge, 0.0)
        capacity = result.capacities.get(edge, 0.0)
        lane_info = result.lane_info.get(edge)
        rows.append(
            {
                "始点": u,
                "終点": v,
                "道路長[m]": round(float(data.get("length", 0.0)), 2),
                "元のlanes": None if lane_info is None else lane_info.raw_value,
                "合計車線数": None if lane_info is None else lane_info.total_lanes,
                "実効車線数": None if lane_info is None else lane_info.effective_lanes,
                "車線数の根拠": None if lane_info is None else lane_info.source,
                "一方通行": None if lane_info is None else lane_info.is_oneway,
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
    "容量は Cₑ=Lₑ(0)(1+α)×道路長補正×車線数補正 で定義します。"
    "車線数が欠損している場合は highway 属性から保守的に推定します。"
)

with st.expander("このモデルの考え方（はじめにお読みください）", expanded=True):
    st.markdown(
        """
1. **事故や災害などで、最初に選んだ道路が利用できなくなった**と考えます。
2. その道路を通るはずだった車が、**ほかの道路へ集まる**と考えます。
3. 車が集まりすぎて道路が処理できる限界を超えると、**その道路も十分に機能できなくなった**ものとして扱います。
4. 利用できない道路を避けて負担がさらに移るため、影響が次々と広がることがあります。

このモデルで道路を「利用できない」とするのは、道路そのものが物理的に壊れたり消えたりすることを意味しません。交通が集中して正常な役割を果たせなくなった状態を、分かりやすく単純化して表現しています。

※実際の交通量や渋滞をそのまま再現するものではなく、**道路のつながり方によって影響がどのように広がるか**を観察するためのモデルです。
        """
    )

with st.sidebar:
    st.header("Road Capacity設定")
    alpha = st.slider("alpha（基本容量余裕）", 0.0, 1.0, 0.5, 0.05)
    length_weight = st.slider(
        "道路長の影響 w",
        0.0,
        2.0,
        1.0,
        0.1,
        help=("平均道路長を超えた分を容量へどれだけ強く反映するかを指定します。0では道路長補正なしです。"
              "1では標準的な影響、2では道路長の影響をより強く反映します。"),
    )
    use_lane_correction = st.toggle(
        "車線数補正を使用する",
        value=True,
        help="OFFにすると車線数を容量へ反映しません。道路長補正との比較に使えます。",
    )
    lane_weight = st.slider(
        "車線数の影響 wₙ",
        0.0,
        2.0,
        1.0,
        0.1,
        disabled=not use_lane_correction,
        help=("実効車線数が1を超えた分を容量へどれだけ反映するかを指定します。0では車線数の影響を反映しません。"
              "1では標準的な影響、2では車線数の影響をより強く反映します。"),
    )
    calculation_mode = st.selectbox(
        "媒介中心性の計算精度",
        list(SAMPLE_OPTIONS),
        index=1,
        help="3 km以上では高速または標準を推奨します。5 kmでは最大64ノードに自動制限します。",
    )
    sample_size = SAMPLE_OPTIONS[calculation_mode]
    seed = st.number_input("seed", min_value=0, value=42, step=1)
    attack_mode = st.radio(
        "初期故障道路の選び方",
        ["高負荷道路", "ランダム道路", "候補から選択", "地図から選択"],
    )

st.caption(
    "alphaは道路全体の余裕の大きさを表します。"
    "道路長と車線数は初期設定では標準的に反映され、"
    "スライダーで影響の大きさを調整できます。"
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
subgraph = project_road_graph(
    extract_radius_subgraph(graph, selected_place.lat, selected_place.lon, radius_m)
)

st.write(
    f"対象ノード数: **{subgraph.number_of_nodes()}** / "
    f"対象道路数: **{subgraph.number_of_edges()}**"
)

effective_sample_size = sample_size
effective_calculation_mode = calculation_mode
if radius_m >= 5000 and (sample_size is None or sample_size > 64):
    effective_sample_size = 64
    effective_calculation_mode = "標準（64ノード・5 km自動制限）"
    st.warning("5 kmでは処理時間とメモリ使用量を抑えるため、媒介中心性計算を64サンプルへ自動制限します。")
elif radius_m >= 3000 and sample_size is None:
    st.warning("3 kmで厳密計算を選ぶと数分以上かかる場合があります。高速または標準を推奨します。")

if subgraph.number_of_edges() == 0:
    st.warning("この範囲には道路がありません。範囲を広げてください。")
    st.stop()

initial_edge: EdgeId | None
if attack_mode == "候補から選択":
    initial_edge = st.selectbox(
        "初期故障道路",
        [canonical_edge(subgraph, u, v) for u, v in subgraph.edges()],
        format_func=lambda edge: edge_label(subgraph, edge),
    )
elif attack_mode == "地図から選択":
    selected_key = (
        round(float(selected_place.lat), 5),
        round(float(selected_place.lon), 5),
        radius_m,
    )
    if st.session_state.get("road_attack_selection_scope") != selected_key:
        st.session_state.road_attack_selection_scope = selected_key
        st.session_state.pop("road_selected_attack_edge", None)

    selected_edge = st.session_state.get("road_selected_attack_edge")
    if selected_edge is not None:
        selected_edge = tuple(selected_edge)
        if not subgraph.has_edge(*selected_edge):
            selected_edge = None
            st.session_state.pop("road_selected_attack_edge", None)

    selection_figure, selectable_edges = build_attack_selection_map(
        subgraph,
        selected_place.lat,
        selected_place.lon,
        radius_m,
        selected_edge,
    )
    st.caption("道路上の半透明ポイントをクリックしてください。選択した道路は黒線で表示されます。")
    selection_event = st.plotly_chart(
        selection_figure,
        width="stretch",
        key=f"road_attack_map_{selected_key}",
        on_select="rerun",
        selection_mode="points",
        config={"displayModeBar": True, "scrollZoom": True},
    )
    selected_points = selection_event.selection.points
    if selected_points:
        point_index = selected_points[0].get("point_index")
        if point_index is not None and 0 <= int(point_index) < len(selectable_edges):
            clicked_edge = selectable_edges[int(point_index)]
            if clicked_edge != selected_edge:
                st.session_state.road_selected_attack_edge = clicked_edge
                st.rerun()

    initial_edge = st.session_state.get("road_selected_attack_edge")
    if initial_edge is None:
        st.info("地図上から初期故障道路を1本選択してください。")
    else:
        initial_edge = tuple(initial_edge)
        st.success(f"選択中: {edge_label(subgraph, initial_edge)}")
else:
    initial_edge = choose_attack_edge(subgraph, attack_mode, int(seed), effective_sample_size)
    st.write(f"初期故障道路: **{edge_label(subgraph, initial_edge)}**")

run_disabled = initial_edge is None
if st.button("Road Capacity Cascadeを実行", type="primary", disabled=run_disabled):
    assert initial_edge is not None
    with st.spinner("エッジ媒介中心性とカスケード故障を計算しています..."):
        st.session_state.road_result = run_road_capacity_cascade(
            subgraph,
            attacked_edges=[initial_edge],
            alpha=alpha,
            length_weight=length_weight,
            lane_weight=lane_weight,
            use_lane_correction=use_lane_correction,
            sample_size=effective_sample_size,
            seed=int(seed),
        )
        st.session_state.road_graph = subgraph
        st.session_state.road_center = (selected_place.lat, selected_place.lon)
        st.session_state.road_radius_m = radius_m
        st.session_state.road_parameters = {
            "alpha": alpha,
            "length_weight": length_weight,
            "use_lane_correction": use_lane_correction,
            "lane_weight": lane_weight,
            "calculation_mode": effective_calculation_mode,
            "sample_size": effective_sample_size,
            "seed": int(seed),
            "attack_mode": attack_mode,
        }

result: RoadCascadeResult | None = st.session_state.get("road_result")
result_graph: nx.Graph | None = st.session_state.get("road_graph")
if result is not None and result_graph is not None:
    st.subheader("ステップごとの負荷率ヒートマップ")
    params = st.session_state.get("road_parameters", {})
    lane_mode_text = (
        f"ON（wₙ={params.get('lane_weight', lane_weight):.2f}）"
        if params.get("use_lane_correction", use_lane_correction)
        else "OFF"
    )
    st.caption(
        f"実行条件: alpha={params.get('alpha', alpha):.2f}, "
        f"道路長の影響w={params.get('length_weight', length_weight):.2f}, "
        f"車線数補正={lane_mode_text}, "
        f"計算精度={params.get('calculation_mode', effective_calculation_mode)}"
    )
    st.caption("道路の色は現在の負荷率、黒は初期故障、濃いピンクは現在Stepの故障、半透明の灰色は過去の故障を表します。")

    max_step = len(result.steps) - 1
    if max_step <= 0:
        step_index = 0
        st.info("カスケード故障は初期故障のみで終了しました。")
    else:
        step_index = st.slider("表示するStep", min_value=0, max_value=max_step, value=0)

    step = result.steps[step_index]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("このStepの新規故障道路", len(step.failed_edges))
    col2.metric("累積故障道路", len(step.cumulative_failed_edges))
    col3.metric("残存道路", step.remaining_edges)
    col4.metric("最大連結成分ノード数", step.largest_component_size)

    finite_ratios = [value for value in step.load_ratios.values() if value != float("inf")]
    st.caption(
        f"最大負荷率: {max(finite_ratios, default=0.0):.3f} / "
        f"容量超過道路数: {sum(value > 1.0 for value in step.load_ratios.values())}"
    )

    center_lat, center_lon = st.session_state.road_center
    result_radius_m = int(st.session_state.get("road_radius_m", radius_m))
    st.plotly_chart(
        build_step_map(result_graph, result, step_index, center_lat, center_lon, result_radius_m),
        width="stretch",
    )

    with st.expander("道路ごとの負荷・容量・車線情報・故障Step"):
        st.dataframe(build_edge_table(result_graph, result), width="stretch", hide_index=True)

    st.warning(
        "このモデルは実交通量、道路幅、信号制御を直接使用していません。"
        "道路長とOSMの車線数（欠損時はhighwayから推定）を容量補正の代理指標として利用しています。"
    )
