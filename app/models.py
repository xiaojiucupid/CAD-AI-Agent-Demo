from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Polygon


@dataclass
class Road:
    """道路红线对象。width 来自图纸文字标注或红线间距推断，单位为米。"""

    name: str
    polygon: Polygon
    centerline: Optional[LineString]
    width: float
    source_layer: str


@dataclass
class Building:
    """建筑对象。height 优先读取 DXF XDATA 中的 HZPLAN/1040 字段。"""

    name: str
    polygon: Polygon
    height: float
    btype: str
    layer: str


@dataclass
class ReviewResult:
    """单栋建筑对单条临接道路的审查结果。"""

    building_name: str
    building_type: str
    height: float
    road_name: str
    road_width: float
    actual_setback: float
    required_setback: float
    passed: bool
    reason: str


@dataclass
class DrawingData:
    roads: list[Road] = field(default_factory=list)
    buildings: list[Building] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    parse_mode: str = "dxf-standard"
    confidence: str = "high"


@dataclass
class Timing:
    t_convert: float = 0.0
    t_parse: float = 0.0
    t_review: float = 0.0
    t_render: float = 0.0

    @property
    def t_total(self) -> float:
        return self.t_convert + self.t_parse + self.t_review + self.t_render
