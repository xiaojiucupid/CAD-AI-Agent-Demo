from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Polygon


# 本文件只定义跨 Agent 传递的数据结构，不包含业务计算逻辑。
# 这样可以让 ParseAgent、ReviewAgent、ReportAgent 之间通过统一模型解耦。


@dataclass
class Road:
    """线性退让控制对象。

    一个 `Road` 不只可以表示普通道路，也可以表示加分项中的高架、匝道、
    高压线等线性控制对象。审查时通过 `kind` 选择不同规则表。
    """

    # name: 报告中展示的道路/线性设施名称，例如“道路1”“高架1”“高压线1”。
    name: str
    # polygon: 道路红线面域或线性设施缓冲面域，用于和建筑轮廓计算边界距离。
    polygon: Polygon
    # centerline: 道路中心线或线性设施中心线；如果输入本身是道路面域，可为空。
    centerline: Optional[LineString]
    # width: 普通道路表示红线宽度，单位米；高压线表示电压等级 kV；高架/匝道可用默认宽度。
    width: float
    # source_layer: 来源图层或解析来源说明，便于在报告/调试时追溯。
    source_layer: str
    # kind: 控制对象类型。road=普通道路，viaduct=高架，ramp=匝道，powerline=高压线。
    kind: str = "road"


@dataclass
class Building:
    """建筑对象。"""

    # name: 建筑名称，优先来自 XDATA 或文字标注，缺失时自动编号。
    name: str
    # polygon: 建筑底层最突出外墙边线近似形成的建筑轮廓面域。
    polygon: Polygon
    # height: 建筑高度，单位米；用于判断低层/多层/高层和 Q 值。
    height: float
    # btype: 建筑类型文本，例如“低层”“多层”“高层”“住宅”等。
    btype: str
    # layer: 建筑来源图层，便于解释识别依据。
    layer: str
    # floors: 建筑楼层数；无法从文字/图层推断时为 0。
    floors: int = 0


@dataclass
class ReviewResult:
    """单栋建筑对单条临接道路/线性设施的审查结果。"""

    # building_name: 被审查建筑名称。
    building_name: str
    # building_type: 建筑类型，用于报告展示。
    building_type: str
    # height: 建筑高度，单位米。
    height: float
    # road_name: 临接道路或线性设施名称。
    road_name: str
    # road_width: 普通道路宽度，或高压线电压等级。
    road_width: float
    # actual_setback: 实际退让距离，单位米。
    actual_setback: float
    # required_setback: 规范要求的理论最小退让距离，单位米。
    required_setback: float
    # passed: 是否合规。True=合规，False=不合规。
    passed: bool
    # reason: 依据链，说明使用了哪张表、哪个条款和计算公式。
    reason: str


@dataclass
class DrawingData:
    """一张 CAD 图纸解析后的结构化数据。"""

    # roads: 图纸中识别出的道路/高架/匝道/高压线等线性控制对象。
    roads: list[Road] = field(default_factory=list)
    # buildings: 图纸中识别出的建筑对象。
    buildings: list[Building] = field(default_factory=list)
    # scenario_core_redlines: 场景化红线候选，key 为场景名，value 为参与退让计算的核心红线对象列表。
    scenario_core_redlines: dict[str, list[Road]] = field(default_factory=dict)
    # scenario_buildings: 场景化建筑候选，key 为场景名，value 为该场景使用的建筑集合。
    scenario_buildings: dict[str, list[Building]] = field(default_factory=dict)
    # parse_warnings: 解析阶段产生的提示或低置信度说明。
    parse_warnings: list[str] = field(default_factory=list)
    # parse_mode: 解析模式标识，例如 dxf-standard 或 dwg-profile。
    parse_mode: str = "dxf-standard"
    # confidence: 解析置信度。high 表示对象识别较完整，low 表示建议人工复核。
    confidence: str = "high"
    # unit_scale: CAD 图纸单位到米的换算系数。标准 DXF 为 1，真实 DWG 常按毫米用 0.001。
    unit_scale: float = 1.0


@dataclass
class Timing:
    """全链路耗时统计。"""

    # t_convert: DWG 转 DXF 或 DXF 透传耗时。
    t_convert: float = 0.0
    # t_parse: CAD 解析耗时。
    t_parse: float = 0.0
    # t_review: 规范推理和合规判定耗时。
    t_review: float = 0.0
    # t_render: 报告和标注图渲染耗时。
    t_render: float = 0.0

    @property
    def t_total(self) -> float:
        """总耗时，等于转换、解析、审查和渲染四部分之和。"""

        return self.t_convert + self.t_parse + self.t_review + self.t_render
