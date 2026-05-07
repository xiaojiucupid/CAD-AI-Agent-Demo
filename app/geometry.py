from __future__ import annotations

from math import isfinite
from typing import Iterable

from shapely.geometry import LineString, Polygon


# CAD 图纸解析后最核心的数据都是几何对象：
# - 建筑轮廓最终转为 Polygon；
# - 道路中心线或边界线最终转为 LineString；
# - 审查距离用 Shapely 的几何距离计算。


def make_polygon(points: Iterable[tuple[float, float]]) -> Polygon:
    """将 CAD 顶点序列转换为合法的 `Polygon`。

    参数：
        points: CAD 多段线顶点，格式为 `[(x, y), ...]`。

    返回：
        Shapely `Polygon` 对象。

    说明：
        CAD 多段线可能存在轻微自交、重复点或闭合误差。`buffer(0)` 是 Shapely
        常用的几何修复方式，可把部分无效多边形修复为可计算对象。
    """

    # polygon：直接由 CAD 点集构造出的初始多边形。
    polygon = Polygon(list(points))
    # 若多边形无效，则尝试修复，避免后续距离/相交计算报错。
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    return polygon


def make_linestring(points: Iterable[tuple[float, float]]) -> LineString:
    """将 CAD 顶点序列转换为 `LineString`。

    参数：
        points: CAD 线或多段线顶点。

    返回：
        Shapely `LineString`，用于表示道路中心线、红线边线等线性对象。
    """

    return LineString(list(points))


def distance_between_boundaries(a: Polygon, b: Polygon) -> float:
    """计算两个面域边界之间的最短距离。

    参数：
        a: 第一个面域，通常是建筑轮廓。
        b: 第二个面域，通常是道路红线面域。

    返回：
        两个边界之间的最短欧氏距离。

    业务含义：
        题目要求计算“建筑后退道路红线距离”。当前 Demo 采用建筑轮廓边界到
        道路红线面域边界的最短距离作为实际退让距离。
    """

    return float(a.boundary.distance(b.boundary))


def safe_round(value: float, digits: int = 2) -> float:
    """安全地保留小数位，用于报告展示。

    参数：
        value: 待格式化数值。
        digits: 保留小数位数，默认 2 位。

    返回：
        有限数值返回四舍五入结果；无穷大或 NaN 返回 0，避免报告显示异常。
    """

    if not isfinite(value):
        return 0.0
    return round(float(value), digits)
