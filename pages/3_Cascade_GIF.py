from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import networkx as nx
from PIL import Image
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hitachi_network.road_cascade import EdgeId, RoadCascadeResult, canonical_edge


RATIO_COLORS = (
    (0.0, 0.4, "#90caf9"),
    (0.4, 0.7, "#4dd0e1"),
    (0.7, 0.9, "#fdd835"),
    (0.9, 1.0, "#fb8c00"),
    (1.0, float("inf"), "#e53935"),
)


def ratio_color(ratio: float) -> str:
    for lower, upper, color in RATIO_COLORS:
        if lower <= ratio < upper:
            return color
    return "#90caf9"


def draw_edge(ax, graph: nx.Graph, edge: EdgeId, *, color: str, width: float, alpha: float = 1.0) -> None:
    u, v = edge
    if u not in graph or v not in graph:
        return
    x1 = float(graph.nodes[u].get("x", 0.0))
    y1 = float(graph.nodes[u].get("y", 0.0))
    x2 = float(graph.nodes[v].get("x", 0.0))
    y2 = float(graph.nodes[v].get("y", 0.0))
    ax.plot([x1, x2], [y1, y2], color=color, linewidth=width, alpha=alpha, solid_capstyle="round")


def build_frame(graph: nx.Graph, result: RoadCascadeResult, step_index: int, dpi: int = 110) -> Image.Image:
    step = result.steps[step_index]
    initial_unavailable = set(result.failed_by_step[0]) if result.failed_by_step else set()
    current_unavailable = set(result.failed_by_step[step_index]) if step_index > 0 else set()
    previous_unavailable: set[EdgeId] = set()
    for edges in result.failed_by_step[1:step_index]:
        previous_unavailable.update(edges)

    cumulative_unavailable = set(step.cumulative_failed_edges)

    fig, ax = plt.subplots(figsize=(9.6, 7.2), dpi=dpi)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f7f7f7")

    for u, v in graph.edges():
        edge = canonical_edge(graph, u, v)
        if edge in cumulative_unavailable:
            continue
        ratio = float(step.load_ratios.get(edge, 0.0))
        width = 1.7 if ratio >= 0.9 else 1.0
        draw_edge(ax, graph, edge, color=ratio_color(ratio), width=width, alpha=0.9)

    for edge in previous_unavailable:
        draw_edge(ax, graph, edge, color="#757575", width=1.8, alpha=0.30)
    for edge in current_unavailable:
        draw_edge(ax, graph, edge, color="#c2185b", width=3.4, alpha=0.95)
    for edge in initial_unavailable:
        draw_edge(ax, graph, edge, color="#111111", width=4.2, alpha=1.0)

    ax.set_aspect("equal", adjustable="datalim")
    ax.margins(0.03)
    ax.axis("off")
    ax.set_title(
        f"Road Capacity Cascade  |  Step {step_index}\n"
        f"New unavailable: {len(step.failed_edges)}   "
        f"Total unavailable: {len(step.cumulative_failed_edges)}",
        fontsize=13,
        pad=12,
    )
    fig.tight_layout(pad=0.8)

    buffer = BytesIO()
    fig.savefig(buffer, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buffer.seek(0)
    image = Image.open(buffer).convert("RGB")
    image.load()
    return image


def build_gif(graph: nx.Graph, result: RoadCascadeResult, duration_ms: int) -> bytes:
    frames = [build_frame(graph, result, index) for index in range(len(result.steps))]
    if not frames:
        raise ValueError("GIFにできるStepがありません。")

    output = BytesIO()
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
        disposal=2,
    )
    return output.getvalue()


st.set_page_config(page_title="Cascade GIF", layout="wide")
st.title("カスケード故障のGIF表示")
st.caption("Road Capacity Cascadeの実行結果を、Step 0から順番に自動再生します。")

result: RoadCascadeResult | None = st.session_state.get("road_result")
graph: nx.Graph | None = st.session_state.get("road_graph")

if result is None or graph is None:
    st.info("先に「Road Capacity Cascade」ページでシミュレーションを実行してください。")
    st.stop()

st.write(f"GIFに含まれるStep数: **{len(result.steps)}**")
duration_ms = st.slider(
    "1つのStepを表示する時間",
    min_value=300,
    max_value=2000,
    value=900,
    step=100,
    format="%d ms",
    help="値を大きくすると、各Stepがゆっくり表示されます。",
)

if st.button("GIFを生成", type="primary"):
    with st.spinner("Stepごとの画像を作成しています..."):
        try:
            st.session_state.road_cascade_gif = build_gif(graph, result, duration_ms)
            st.session_state.road_cascade_gif_duration = duration_ms
        except Exception as exc:
            st.error(f"GIFの生成に失敗しました: {exc}")

gif_bytes = st.session_state.get("road_cascade_gif")
if gif_bytes:
    st.subheader("自動再生")
    st.image(gif_bytes, width="stretch")
    st.download_button(
        "GIFをダウンロード",
        data=gif_bytes,
        file_name="road_capacity_cascade.gif",
        mime="image/gif",
    )
    st.caption(
        "青〜赤は道路の負荷率、黒は最初に利用できない道路、"
        "濃いピンクはそのStepで新たに利用できなくなった道路です。"
    )
