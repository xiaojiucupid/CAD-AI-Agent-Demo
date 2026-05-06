from __future__ import annotations

from math import isfinite
from typing import Iterable

from shapely.geometry import LineString, Polygon


def make_polygon(points: Iterable[tuple[float, float]]) -> Polygon:
    """将 DXF 顶点转换为合法 Polygon。"""

    polygon = Polygon(list(points))
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def make_linestring(points: Iterable[tuple[float, float]]) -> LineString:
    return LineString(list(points))


def distance_between_boundaries(a: Polygon, b: Polygon) -> float:
    """计算两个图形边界之间的最短距离。"""

    return float(a.boundary.distance(b.boundary))


def safe_round(value: float, digits: int = 2) -> float:
    if not isfinite(value):
        return 0.0
    return round(float(value), digits)
