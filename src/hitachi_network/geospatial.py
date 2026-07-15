from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Hashable, Iterable, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import networkx as nx


DEFAULT_NOMINATIM_USER_AGENT = "hitachi-traffic-network-starter/1.0 (open-campus demo)"
DEFAULT_NOMINATIM_ENDPOINT = "https://nominatim.openstreetmap.org/search"


@dataclass(frozen=True)
class PlaceCandidate:
    display_name: str
    lat: float
    lon: float
    importance: float | None = None
    osm_id: int | None = None
    osm_type: str | None = None
    query: str | None = None


def build_search_queries(query: str, *, supplement: str = "茨城県 日立市") -> list[str]:
    stripped = query.strip()
    if not stripped:
        return []

    queries = [stripped]
    if supplement and supplement not in stripped:
        augmented = f"{stripped} {supplement}".strip()
        if augmented not in queries:
            queries.insert(0, augmented)
    return queries


def nominatim_result_to_candidate(result: dict[str, object], *, query: str | None = None) -> PlaceCandidate:
    return PlaceCandidate(
        display_name=str(result.get("display_name", "")),
        lat=float(result["lat"]),
        lon=float(result["lon"]),
        importance=float(result["importance"]) if result.get("importance") is not None else None,
        osm_id=int(float(result["osm_id"])) if result.get("osm_id") is not None else None,
        osm_type=str(result.get("osm_type")) if result.get("osm_type") is not None else None,
        query=query,
    )


def _dedupe_candidates(candidates: Sequence[PlaceCandidate]) -> list[PlaceCandidate]:
    seen: set[tuple[float, float, str]] = set()
    unique_candidates: list[PlaceCandidate] = []
    for candidate in candidates:
        key = (round(candidate.lat, 7), round(candidate.lon, 7), candidate.display_name)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def search_places(query: str, *, limit: int = 5, user_agent: str = DEFAULT_NOMINATIM_USER_AGENT) -> list[PlaceCandidate]:
    """Search Nominatim for place candidates.

    The caller is responsible for caching the result if needed.
    """
    candidates: list[PlaceCandidate] = []
    for search_query in build_search_queries(query):
        params = urlencode(
            {
                "q": search_query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": str(limit),
                "accept-language": "ja",
            }
        )
        request = Request(
            f"{DEFAULT_NOMINATIM_ENDPOINT}?{params}",
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )
        with urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candidates.extend(nominatim_result_to_candidate(item, query=search_query) for item in payload)
        if candidates:
            break
    return _dedupe_candidates(candidates)


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_earth_m = 6_371_000.0
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    return 2 * radius_earth_m * asin(sqrt(a))


def nodes_within_radius(graph: nx.Graph, center_lat: float, center_lon: float, radius_m: float) -> list[Hashable]:
    selected_nodes: list[Hashable] = []
    for node, data in graph.nodes(data=True):
        node_lon = float(data.get("x", 0.0))
        node_lat = float(data.get("y", 0.0))
        if haversine_distance_m(center_lat, center_lon, node_lat, node_lon) <= radius_m:
            selected_nodes.append(node)
    return selected_nodes


def extract_radius_subgraph(graph: nx.Graph, center_lat: float, center_lon: float, radius_m: float) -> nx.Graph:
    selected_nodes = nodes_within_radius(graph, center_lat, center_lon, radius_m)
    return graph.subgraph(selected_nodes).copy()


def nearest_node_to_location(graph: nx.Graph, center_lat: float, center_lon: float) -> Hashable:
    best_node: Hashable | None = None
    best_distance = float("inf")
    for node, data in graph.nodes(data=True):
        node_lon = float(data.get("x", 0.0))
        node_lat = float(data.get("y", 0.0))
        distance = haversine_distance_m(center_lat, center_lon, node_lat, node_lon)
        if distance < best_distance:
            best_distance = distance
            best_node = node

    if best_node is None:
        raise ValueError("graph has no nodes")
    return best_node


def build_google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def node_label_with_location(graph: nx.Graph, node: Hashable) -> str:
    data = graph.nodes[node]
    lat = float(data.get("y", 0.0))
    lon = float(data.get("x", 0.0))

    nearby_names: list[str] = []
    for _, _, edge_data in graph.edges(node, data=True):
        raw_name = edge_data.get("name") or edge_data.get("ref") or edge_data.get("highway")
        if not raw_name:
            continue
        if isinstance(raw_name, str):
            for part in raw_name.split(","):
                candidate = part.strip()
                if candidate and candidate not in nearby_names:
                    nearby_names.append(candidate)
        else:
            candidate = str(raw_name)
            if candidate and candidate not in nearby_names:
                nearby_names.append(candidate)

    nearby_text = nearby_names[0] if nearby_names else "近隣名称なし"
    return f"{lat:.6f}, {lon:.6f} / {nearby_text}"
