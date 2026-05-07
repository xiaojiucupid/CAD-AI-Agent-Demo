from __future__ import annotations

from app.geometry import distance_between_boundaries, safe_round
from app.models import DrawingData, ReviewResult
from app.rules import apply_intersection_rule, classify_building_category, lookup_table_3_2, lookup_table_3_3, lookup_table_3_4


# ADJACENT_DISTANCE_LIMIT: 除最近道路外，60m 内的其他道路也视为可能临接道路。
ADJACENT_DISTANCE_LIMIT = 60.0
# INTERSECTION_ROAD_GAP_LIMIT: 两条道路面域距离小于该阈值时，认为道路相交或近接。
INTERSECTION_ROAD_GAP_LIMIT = 1.0
# MAX_REVIEW_SETBACK_DISTANCE: 超过该距离的道路不参与该建筑审查，避免远处道路误匹配。
MAX_REVIEW_SETBACK_DISTANCE = 120.0
# MAX_ADJACENT_ROADS_PER_BUILDING: 每栋建筑最多保留的临接道路数量，避免报告爆炸。
MAX_ADJACENT_ROADS_PER_BUILDING = 4


def _is_intersection_context(adjacent_roads: list[tuple[object, float]]) -> bool:
    """判断建筑是否位于道路交叉口四周。

    参数：
        adjacent_roads: 建筑临接道路列表，每项为 `(Road, 实际距离)`。

    返回：
        True 表示建筑同时临接的道路之间相交/近接，可触发第 3 款；否则 False。

    说明：
        仅“建筑离两条路都近”不足以认定为交叉口，还需要道路红线面域本身
        相交或近接。这样可以避免平行道路误触发交叉口规则。
    """

    if len(adjacent_roads) < 2:
        return False
    # roads: 只取 Road 对象，忽略距离值。
    roads = [item[0] for item in adjacent_roads]
    for idx, road_a in enumerate(roads):
        for road_b in roads[idx + 1 :]:
            if road_a.polygon.distance(road_b.polygon) <= INTERSECTION_ROAD_GAP_LIMIT:
                return True
    return False


def review_drawing(data: DrawingData) -> list[ReviewResult]:
    """执行逐栋建筑退让审查。

    参数：
        data: ParseAgent 输出的结构化图纸数据。

    返回：
        每栋建筑对每条临接道路/线性控制对象的审查结果列表。

    审查流程：
        1. 计算建筑到所有道路/线性设施的边界距离。
        2. 筛选最近和一定范围内的临接对象。
        3. 普通道路查询表 3-2，并叠加第 3 款交叉口规则。
        4. 高架/匝道查询表 3-3。
        5. 高压线查询表 3-4。
        6. 用 `actual + 0.1 >= required` 判定是否合规。
    """

    # results: 最终返回给 ReportAgent 的逐栋审查结果。
    results: list[ReviewResult] = []
    if not data.roads:
        return results

    for building in data.buildings:
        # distances: 当前建筑到每个线性控制对象的实际边界距离，乘 unit_scale 后统一为米。
        distances = [(road, distance_between_boundaries(building.polygon, road.polygon) * data.unit_scale) for road in data.roads]
        # 按距离从近到远排序，最近对象通常就是临接道路。
        distances.sort(key=lambda item: item[1])
        # relevant_distances: 过滤掉过远道路，避免报告中出现与建筑无关的道路。
        relevant_distances = [(road, dist) for road, dist in distances if dist <= MAX_REVIEW_SETBACK_DISTANCE]
        if not relevant_distances:
            continue
        # nearest_distance: 当前建筑最近道路距离。
        nearest_distance = relevant_distances[0][1]
        # adjacent: 临接道路集合。最近道路必保留，60m 内道路也保留，用于交叉口判断。
        adjacent = [
            (road, dist)
            for road, dist in relevant_distances
            if dist <= nearest_distance + 0.1 or dist <= ADJACENT_DISTANCE_LIMIT
        ][:MAX_ADJACENT_ROADS_PER_BUILDING]
        # is_intersection: 是否处于道路交叉口上下文。
        is_intersection = _is_intersection_context(adjacent)
        # intersection_widths: 交叉口规则只对普通道路有意义，这里保留道路宽度列表传给规则函数。
        intersection_widths = [road.width for road, _dist in adjacent] if is_intersection else []

        for road, actual in adjacent:
            # category: 低层/多层/高层分类，用于表 3-2、表 3-3 和第 3 款。
            category = classify_building_category(building.height, building.btype)
            if road.kind == "viaduct":
                # 高架按表 3-3 审查。
                rule = lookup_table_3_3("viaduct", category, building.btype)
                required, extra_reason = rule.minimum_setback, "第4款：沿城市高架道路两侧建筑按表3-3控制"
            elif road.kind == "ramp":
                # 匝道按表 3-3 审查。
                rule = lookup_table_3_3("ramp", category, building.btype)
                required, extra_reason = rule.minimum_setback, "第4款：沿匝道建筑按表3-3控制"
            elif road.kind == "powerline":
                # 高压线按表 3-4 审查，road.width 在此表示电压等级。
                rule = lookup_table_3_4(road.width)
                required, extra_reason = rule.minimum_setback, "第8款：后退电力线地面投影边线距离按表3-4控制"
            else:
                # 普通道路先查表 3-2，再与第 3 款交叉口控制值取大。
                rule = lookup_table_3_2(building.height, road.width, building.btype)
                required, extra_reason = apply_intersection_rule(
                    rule.minimum_setback,
                    len(intersection_widths),
                    intersection_widths,
                    category,
                )
            # passed: 允许 0.1m 误差，符合题目评分说明。
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
