from __future__ import annotations

from pathlib import Path
from typing import Literal

import networkx as nx
import pandas as pd

GraphMode = Literal["directed", "undirected"]


def _to_bool(value: object) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def load_road_graph(
    nodes_path: str | Path,
    edges_path: str | Path,
    *,
    mode: GraphMode = "directed",
) -> nx.MultiGraph | nx.MultiDiGraph:
    """Load OSM-style node/edge CSV files into a NetworkX graph.

    Node IDs are read from ``osmid``. Edge length is stored in metres under
    ``length``. The directed graph preserves the rows in the edge CSV, which
    is useful because one-way restrictions are already reflected by OSMnx
    exports in many datasets.
    """
    nodes_path = Path(nodes_path)
    edges_path = Path(edges_path)
    if not nodes_path.exists():
        raise FileNotFoundError(f"Node CSV not found: {nodes_path}")
    if not edges_path.exists():
        raise FileNotFoundError(f"Edge CSV not found: {edges_path}")

    nodes = pd.read_csv(nodes_path)
    edges = pd.read_csv(edges_path)

    required_node_cols = {"osmid", "x", "y"}
    required_edge_cols = {"u", "v", "key", "length"}
    if missing := required_node_cols - set(nodes.columns):
        raise ValueError(f"Missing node columns: {sorted(missing)}")
    if missing := required_edge_cols - set(edges.columns):
        raise ValueError(f"Missing edge columns: {sorted(missing)}")

    graph: nx.MultiGraph | nx.MultiDiGraph
    graph = nx.MultiDiGraph() if mode == "directed" else nx.MultiGraph()

    for row in nodes.itertuples(index=False):
        attrs = row._asdict()
        node_id = int(attrs.pop("osmid"))
        attrs["x"] = float(attrs["x"])
        attrs["y"] = float(attrs["y"])
        graph.add_node(node_id, **attrs)

    for row in edges.itertuples(index=False):
        attrs = row._asdict()
        u = int(attrs.pop("u"))
        v = int(attrs.pop("v"))
        key = int(attrs.pop("key"))
        attrs["length"] = float(attrs["length"])
        attrs["oneway"] = _to_bool(attrs.get("oneway"))
        graph.add_edge(u, v, key=key, **attrs)

    graph.graph["crs"] = "EPSG:4326"
    graph.graph["source_nodes"] = str(nodes_path)
    graph.graph["source_edges"] = str(edges_path)
    return graph
