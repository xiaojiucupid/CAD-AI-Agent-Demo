from shapely.geometry import Polygon

from app.geometry import distance_between_boundaries
from app.models import Building, DrawingData, Road
from app.reviewer import review_drawing


def test_distance_between_building_and_road_boundaries():
    """退让距离算法：建筑边界到道路红线边界的最短欧氏距离应可被精确验证。"""

    road = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    building = Polygon([(15, 2), (20, 2), (20, 8), (15, 8)])

    assert distance_between_boundaries(building, road) == 5.0


def test_review_drawing_pass_and_fail_results():
    """完整合规判定链路：同一条道路旁的两栋建筑应分别判定为合规和不合规。"""

    road = Road(
        name="测试道路 W=24m",
        polygon=Polygon([(0, 0), (10, 0), (10, 100), (0, 100)]),
        centerline=None,
        width=24.0,
        source_layer="ROAD_REDLINE",
    )
    passed_building = Building(
        name="合规建筑",
        polygon=Polygon([(20, 10), (30, 10), (30, 20), (20, 20)]),
        height=18.0,
        btype="multi",
        layer="BUILDING_MULTI",
    )
    failed_building = Building(
        name="不合规建筑",
        polygon=Polygon([(14, 30), (24, 30), (24, 40), (14, 40)]),
        height=18.0,
        btype="multi",
        layer="BUILDING_MULTI",
    )

    results = review_drawing(DrawingData(roads=[road], buildings=[passed_building, failed_building]))
    result_by_name = {result.building_name: result for result in results}

    assert result_by_name["合规建筑"].actual_setback == 10.0
    assert result_by_name["合规建筑"].required_setback == 8.0
    assert result_by_name["合规建筑"].passed is True

    assert result_by_name["不合规建筑"].actual_setback == 4.0
    assert result_by_name["不合规建筑"].required_setback == 8.0
    assert result_by_name["不合规建筑"].passed is False
