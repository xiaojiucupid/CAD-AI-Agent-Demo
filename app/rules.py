from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleMatch:
    q_value: float
    minimum_setback: float
    basis: str


@dataclass(frozen=True)
class Table32Row:
    """表 3-2 的结构化行：道路宽度分档对应不同建筑类别的退让基数。"""

    width_band: str
    arcade_low: float
    low: float
    multi: float
    high_factor: float


WIDTH_BAND_LABELS = {
    "le20": "14m≤道路红线宽度≤20m（14m以下参照本档）",
    "20to40": "20m<道路红线宽度≤40m",
    "gt40": "道路红线宽度>40m",
}


# 《杭州市城市规划管理技术规定（2026）》表（3-2）：
# 道路宽度 14（含）—20（含）：低层骑楼2、低层3、多层5、高层5Q；
# 道路宽度 20—40（含）：低层骑楼3、低层5、多层8、高层8Q；
# 道路宽度 ＞40：低层骑楼5、低层8、多层10、高层10Q。
TABLE_3_2_ROWS: tuple[Table32Row, ...] = (
    Table32Row("le20", arcade_low=2.0, low=3.0, multi=5.0, high_factor=5.0),
    Table32Row("20to40", arcade_low=3.0, low=5.0, multi=8.0, high_factor=8.0),
    Table32Row("gt40", arcade_low=5.0, low=8.0, multi=10.0, high_factor=10.0),
)


def classify_width_band(width: float) -> str:
    """根据道路红线宽度划分表 3-2 分档。"""

    if width <= 20:
        return "le20"
    if width <= 40:
        return "20to40"
    return "gt40"


def infer_q_value(height: float) -> float:
    """按附件 2 查询高层建筑高度综合影响系数 Q。"""

    if height <= 50:
        return 1.0
    if height <= 75:
        return 1.2
    if height <= 100:
        return 1.4
    if height <= 200:
        return 1.6
    return 1.8


def _match_table_3_2_row(road_width: float) -> Table32Row:
    width_band = classify_width_band(road_width)
    for row in TABLE_3_2_ROWS:
        if row.width_band == width_band:
            return row
    raise ValueError(f"无法匹配表3-2：road_width={road_width}")


def classify_building_category(height: float, building_type: str = "") -> str:
    """识别表 3-2 中的建筑类别。

    图纸若在图层/名称中显式包含“骑楼”，优先按低层骑楼处理；否则按照附件 2
    的高度定义区分低层、多层、高层。住宅与公共建筑高层阈值不同，当前输入未
    提供用地/功能字段时采用更严格的公共建筑 24m 阈值。
    """

    text = building_type.upper()
    if "骑楼" in building_type or "ARCADE" in text:
        return "arcade_low"
    if height <= 10:
        return "low"
    if height <= 24:
        return "multi"
    return "high"


def lookup_table_3_2(height: float, road_width: float, building_type: str = "") -> RuleMatch:
    """查询表 3-2 得到理论最小退让。"""

    row = _match_table_3_2_row(road_width)
    category = classify_building_category(height, building_type)
    q_value = infer_q_value(height)
    if category == "arcade_low":
        minimum = row.arcade_low
        category_label = "低层骑楼"
        formula = f"{minimum}m"
    elif category == "low":
        minimum = row.low
        category_label = "低层建筑"
        formula = f"{minimum}m"
    elif category == "multi":
        minimum = row.multi
        category_label = "多层建筑"
        formula = f"{minimum}m"
    else:
        minimum = row.high_factor * q_value
        category_label = "高层建筑"
        formula = f"{row.high_factor:g}Q={row.high_factor:g}×{q_value:g}={minimum:g}m"
    return RuleMatch(
        q_value=q_value,
        minimum_setback=minimum,
        basis=f"表3-2：{WIDTH_BAND_LABELS[row.width_band]}，{category_label}，退让={formula}",
    )


def intersection_corner_setback(road_widths: list[float]) -> tuple[float, str]:
    """道路交叉口四周建筑后退红线的附加审查要求。

    触发条件由 reviewer 根据“建筑同时邻接两条及以上道路且道路红线互相相交/
    近接”判断。本函数只负责把相交道路等级映射为第 3 款的加严距离。
    """

    if len(road_widths) < 2:
        return 0.0, "非交叉口情形"
    max_width = max(road_widths)
    # 第 3 款要求交叉口四周低、多层不小于 5m，高层不小于 8m，且与表 3-2 取大。
    # 为兼容旧入口，这里只返回交叉口最低控制值，调用方用 max 取严。
    if max_width > 40:
        return 8.0, "第3款：道路交叉口四周建筑控制值8.0m"
    return 5.0, "第3款：道路交叉口四周建筑控制值5.0m"


def apply_intersection_rule(required_setback: float, road_count: int, road_widths: list[float] | None = None) -> tuple[float, str]:
    """兼容旧测试的交叉口规则入口。"""

    widths = road_widths or ([20.0] * road_count)
    corner_required, reason = intersection_corner_setback(widths)
    return max(required_setback, corner_required), reason
