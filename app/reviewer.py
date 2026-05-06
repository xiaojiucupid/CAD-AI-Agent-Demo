from __future__ import annotations

from app.geometry import distance_between_boundaries, safe_round
from app.models import DrawingData, ReviewResult
from app.rules import apply_intersection_rule, lookup_table_3_2


ADJACENT_DISTANCE_LIMIT = 60.0
INTERSECTION_ROAD_GAP_LIMIT = 1.0


def _is_intersection_context(adjacent_roads: list[tuple[object, float]]) -> bool:
    """判断建筑是否位于道路交叉口四周。

    仅“离两条路都近”不足以认定交叉口，还需要这些道路红线本身相交或近接。
    因此这里对所有临接道路两两检查红线面域距离，避免平行道路误触发第 3 款。
    """

    if len(adjacent_roads) < 2:
        return False
    roads = [item[0] for item in adjacent_roads]
    for idx, road_a in enumerate(roads):
        for road_b in roads[idx + 1 :]:
            if road_a.polygon.distance(road_b.polygon) <= INTERSECTION_ROAD_GAP_LIMIT:
                return True
    return False


def review_drawing(data: DrawingData) -> list[ReviewResult]:
    """执行逐栋建筑退让审查。

    先找出每栋建筑与道路红线的边界距离，筛选临接道路；随后查询表 3-2，
    并在道路红线几何上确认为交叉口时叠加第 3 款要求。距离采用建筑轮廓到
    道路红线面域边界的最短欧氏距离，单位沿用 CAD 米制。
    """

    results: list[ReviewResult] = []
    if not data.roads:
        return results

    for building in data.buildings:
        distances = [(road, distance_between_boundaries(building.polygon, road.polygon)) for road in data.roads]
        distances.sort(key=lambda item: item[1])
        nearest_distance = distances[0][1]
        adjacent = [
            (road, dist)
            for road, dist in distances
            if dist <= nearest_distance + 0.1 or dist <= ADJACENT_DISTANCE_LIMIT
        ]
        is_intersection = _is_intersection_context(adjacent)
        intersection_widths = [road.width for road, _dist in adjacent] if is_intersection else []

        for road, actual in adjacent:
            rule = lookup_table_3_2(building.height, road.width, building.btype)
            required, extra_reason = apply_intersection_rule(
                rule.minimum_setback,
                len(intersection_widths),
                intersection_widths,
            )
            passed = actual + 0.1 >= required
            results.append(
                ReviewResult(
                    building_name=building.name,
                    building_type=building.btype,
                    height=safe_round(building.height),
                    road_name=road.name,
                    road_width=safe_round(road.width),
                    actual_setback=safe_round(actual),
                    required_setback=safe_round(required),
                    passed=passed,
                    reason=f"{rule.basis}；{extra_reason}",
                )
            )

    return results
