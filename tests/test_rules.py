from shapely.geometry import Polygon

from app.geometry import distance_between_boundaries
from app.models import Building, DrawingData, Road
from app.reviewer import review_drawing
from app.rules import apply_intersection_rule, classify_building_category, classify_width_band, infer_q_value, lookup_table_3_2, lookup_table_3_3, lookup_table_3_4


def test_width_band():
    assert classify_width_band(14) == "le20"
    assert classify_width_band(20) == "le20"
    assert classify_width_band(24) == "20to40"
    assert classify_width_band(36) == "20to40"
    assert classify_width_band(45) == "gt40"


def test_q_value_and_lookup():
    assert infer_q_value(18) == 1.0
    assert infer_q_value(60) == 1.2
    assert classify_building_category(9, "低层") == "low"
    assert classify_building_category(18, "多层") == "multi"
    assert classify_building_category(90, "高层") == "high"
    assert lookup_table_3_2(18, 24, "多层").minimum_setback == 8
    assert lookup_table_3_2(90, 36, "高层").minimum_setback == 11.2


def test_intersection_rule():
    assert apply_intersection_rule(10, 1)[0] == 10
    assert apply_intersection_rule(4, 2, [18, 18], "multi")[0] == 5
    assert apply_intersection_rule(6, 2, [24, 30], "multi")[0] == 6
    assert apply_intersection_rule(6, 2, [24, 30], "high")[0] == 8


def test_lookup_table_3_3_and_3_4():
    assert lookup_table_3_3("viaduct", "multi", "居住建筑").minimum_setback == 30
    assert lookup_table_3_3("viaduct", "high", "居住建筑").minimum_setback == 40
    assert lookup_table_3_3("ramp", "multi", "商业建筑").minimum_setback == 10
    assert lookup_table_3_3("ramp", "high", "商业建筑").minimum_setback == 15
    assert lookup_table_3_4(500).minimum_setback == 30
    assert lookup_table_3_4(220).minimum_setback == 15
    assert lookup_table_3_4(110).minimum_setback == 10


def test_setback_distance_between_building_and_road_redline():
    """退让距离算法：建筑边界到道路红线边界的最短距离应为 12m。"""

    road = Polygon([(0, 0), (100, 0), (100, 10), (0, 10)])
    building = Polygon([(20, 22), (40, 22), (40, 42), (20, 42)])

    assert distance_between_boundaries(building, road) == 12


def test_review_drawing_compliance_pass_and_fail():
    """完整合规判定链路：同一道路下同时验证合规建筑和不合规建筑。"""

    road = Road(
        name="测试道路 W=24m",
        polygon=Polygon([(0, 0), (100, 0), (100, 10), (0, 10)]),
        centerline=None,
        width=24,
        source_layer="ROAD_REDLINE",
    )
    compliant_building = Building(
        name="合规建筑",
        polygon=Polygon([(20, 22), (40, 22), (40, 42), (20, 42)]),
        height=18,
        btype="multi",
        layer="BUILDING_MULTI",
    )
    non_compliant_building = Building(
        name="不合规建筑",
        polygon=Polygon([(50, 15), (70, 15), (70, 35), (50, 35)]),
        height=18,
        btype="multi",
        layer="BUILDING_MULTI",
    )

    results = review_drawing(
        DrawingData(
            roads=[road],
            buildings=[compliant_building, non_compliant_building],
        )
    )

    verdicts = {result.building_name: result.passed for result in results}
    actual_setbacks = {result.building_name: result.actual_setback for result in results}
    required_setbacks = {result.building_name: result.required_setback for result in results}

    assert verdicts["合规建筑"] is True
    assert verdicts["不合规建筑"] is False
    assert actual_setbacks["合规建筑"] == 12
    assert actual_setbacks["不合规建筑"] == 5
    assert required_setbacks["合规建筑"] == 8
    assert required_setbacks["不合规建筑"] == 8
