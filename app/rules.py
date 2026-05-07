from __future__ import annotations

from dataclasses import dataclass


# 本文件是规范规则引擎，负责把《杭州市城市规划管理技术规定（2026）》中的
# 表格和条文转成可执行函数。解析器只负责提取图形对象，审查器只负责调用
# 这些函数，不在其他地方硬编码规范数值。


@dataclass(frozen=True)
class RuleMatch:
    """一次规范查询的结果。"""

    # q_value: 高层建筑高度综合影响系数 Q。非高层或非 Q 表可返回 1。
    q_value: float
    # minimum_setback: 理论最小退让距离，单位米。
    minimum_setback: float
    # basis: 文字依据链，用于 HTML 报告展示。
    basis: str


@dataclass(frozen=True)
class Table32Row:
    """表 3-2 的结构化行。"""

    # width_band: 道路宽度分档标识，例如 le20、20to40、gt40。
    width_band: str
    # arcade_low: 低层骑楼最小退让距离。
    arcade_low: float
    # low: 低层建筑最小退让距离。
    low: float
    # multi: 多层建筑最小退让距离。
    multi: float
    # high_factor: 高层建筑 Q 值乘数，例如 5Q、8Q、10Q 中的 5/8/10。
    high_factor: float


# WIDTH_BAND_LABELS: 道路宽度分档的人类可读说明，用于报告依据链。
WIDTH_BAND_LABELS = {
    "le20": "14m≤道路红线宽度≤20m（14m以下参照本档）",
    "20to40": "20m<道路红线宽度≤40m",
    "gt40": "道路红线宽度>40m",
}


# TABLE_3_2_ROWS: 《杭州市城市规划管理技术规定（2026）》表（3-2）的结构化版本。
TABLE_3_2_ROWS: tuple[Table32Row, ...] = (
    Table32Row("le20", arcade_low=2.0, low=3.0, multi=5.0, high_factor=5.0),
    Table32Row("20to40", arcade_low=3.0, low=5.0, multi=8.0, high_factor=8.0),
    Table32Row("gt40", arcade_low=5.0, low=8.0, multi=10.0, high_factor=10.0),
)


def classify_width_band(width: float) -> str:
    """根据道路红线宽度划分表 3-2 分档。

    参数：
        width: 道路红线宽度，单位米。

    返回：
        `le20`、`20to40` 或 `gt40`。
    """

    if width <= 20:
        return "le20"
    if width <= 40:
        return "20to40"
    return "gt40"


def infer_q_value(height: float) -> float:
    """按附件 2 查询高层建筑高度综合影响系数 Q。

    参数：
        height: 建筑高度，单位米。

    返回：
        Q 值。规范分段为 1.0、1.2、1.4、1.6、1.8。
    """

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
    """根据道路宽度找到表 3-2 对应行。"""

    # width_band: 道路宽度对应的分档标识。
    width_band = classify_width_band(road_width)
    for row in TABLE_3_2_ROWS:
        if row.width_band == width_band:
            return row
    raise ValueError(f"无法匹配表3-2：road_width={road_width}")


def classify_building_category(height: float, building_type: str = "") -> str:
    """识别表 3-2 中的建筑类别。

    参数：
        height: 建筑高度，单位米。
        building_type: 从图层、文字或名称中提取到的建筑类型描述。

    返回：
        `arcade_low`、`low`、`multi` 或 `high`。

    说明：
        题目图纸通常未提供住宅/公共建筑功能字段，因此 Demo 采用较保守的
        公共建筑高层阈值：高度大于 24m 按高层处理。
    """

    # text: 英文/拼音关键字匹配时使用的大写字符串。
    text = building_type.upper()
    if "骑楼" in building_type or "ARCADE" in text:
        return "arcade_low"
    if height <= 10:
        return "low"
    if height <= 24:
        return "multi"
    return "high"


def lookup_table_3_2(height: float, road_width: float, building_type: str = "") -> RuleMatch:
    """查询表 3-2，得到建筑后退道路红线的理论最小距离。"""

    # row: 当前道路宽度所在的表 3-2 行。
    row = _match_table_3_2_row(road_width)
    # category: 当前建筑在表 3-2 中的类别。
    category = classify_building_category(height, building_type)
    # q_value: 高层建筑 Q 值；低层/多层也计算但不参与公式。
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
        # 高层建筑按 5Q / 8Q / 10Q 计算。
        minimum = row.high_factor * q_value
        category_label = "高层建筑"
        formula = f"{row.high_factor:g}Q={row.high_factor:g}×{q_value:g}={minimum:g}m"

    return RuleMatch(
        q_value=q_value,
        minimum_setback=minimum,
        basis=f"表3-2：{WIDTH_BAND_LABELS[row.width_band]}，{category_label}，退让={formula}",
    )


def intersection_corner_setback(building_category: str, road_count: int) -> tuple[float, str]:
    """道路交叉口四周建筑后退红线的附加要求。

    参数：
        building_category: 建筑类别，来自 `classify_building_category()`。
        road_count: 建筑所在交叉口上下文中的临接道路数量。

    返回：
        `(交叉口控制距离, 条文说明)`。
    """

    if road_count < 2:
        return 0.0, "非交叉口情形"
    if building_category == "high":
        return 8.0, "第3款：道路交叉口四周高层建筑控制值8.0m"
    return 5.0, "第3款：道路交叉口四周低、多层建筑控制值5.0m"


def lookup_table_3_3(facility_kind: str, building_category: str, building_type: str = "") -> RuleMatch:
    """查询表 3-3：建筑物离高架和匝道的距离。

    参数：
        facility_kind: `viaduct` 表示高架，`ramp` 表示匝道。
        building_category: 低/多/高层类别。
        building_type: 建筑功能描述，用于识别居住、学校、医院类敏感建筑。
    """

    # is_sensitive: 是否属于居住、学校、医院等敏感建筑。
    is_sensitive = any(keyword in building_type for keyword in ("居住", "住宅", "学校", "医院", "幼儿园", "托儿所", "宿舍", "疗养"))
    # is_high: 是否为高层建筑。
    is_high = building_category == "high"
    # kind: 规范设施类型，只允许高架或匝道。
    kind = "ramp" if facility_kind == "ramp" else "viaduct"

    if kind == "viaduct":
        minimum = 40.0 if is_sensitive and is_high else 30.0 if is_sensitive else 20.0 if is_high else 15.0
        label = "高架"
    else:
        minimum = 30.0 if is_sensitive else 15.0 if is_high else 10.0
        label = "匝道"

    group = "居住、学校和医院类建筑" if is_sensitive else "其他建筑"
    level = "高层" if is_high else "低、多层"
    return RuleMatch(1.0, minimum, f"表3-3：{label}，{group}，{level}，退让={minimum:g}m")


def lookup_table_3_4(voltage_kv: float) -> RuleMatch:
    """查询表 3-4：建筑物与高压架空线的距离。

    参数：
        voltage_kv: 高压线电压等级，单位 kV。
    """

    if voltage_kv >= 500:
        minimum = 30.0
        label = "500kV"
    elif voltage_kv >= 220:
        minimum = 15.0
        label = "220kV"
    else:
        minimum = 10.0
        label = "110kV"
    return RuleMatch(1.0, minimum, f"表3-4：高压架空线{label}，建筑最小后退距离={minimum:g}m")


def apply_intersection_rule(
    required_setback: float,
    road_count: int,
    road_widths: list[float] | None = None,
    building_category: str = "multi",
) -> tuple[float, str]:
    """将第 3 款交叉口规则叠加到表 3-2 结果上。

    参数：
        required_setback: 表 3-2 已计算出的普通路段退让值。
        road_count: 交叉口上下文中的道路数量。
        road_widths: 兼容旧测试保留的参数，当前不参与计算。
        building_category: 建筑类别。

    返回：
        `(取严后的退让距离, 交叉口规则说明)`。
    """

    _ = road_widths
    corner_required, reason = intersection_corner_setback(building_category, road_count)
    return max(required_setback, corner_required), reason
