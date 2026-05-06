from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DWGProfile:
    """真实 DWG 的通用解析配置。

    不是绑定某一张图的绝对坐标，而是定义常见总平图层的角色、过滤阈值和
    置信度判断规则。其他 DWG 可以通过扩展 profile 覆盖这些字段。
    """

    mode: str = "balanced"
    label: str = "平衡识别模式"
    description: str = "保留主要建筑/道路候选并做适度过滤，适合默认 Demo 审查。"
    building_insert_layers: tuple[str, ...] = ("G-BLDG-OTLN",)
    building_polyline_layers: tuple[str, ...] = ("G-BLDG-HIGH", "G-BLDG-MULT")
    building_hatch_layers: tuple[str, ...] = ("G-FRIE-FLWL",)
    road_layer_keywords: tuple[str, ...] = ("G_DRIV_ROAD", "G-ROAD", "ROAD", "道路", "DRIV")
    redline_layer_keywords: tuple[str, ...] = ("REDL", "红线", "SITE-PROP", "征地")
    min_building_area: float = 10_000_000.0
    max_building_area: float = 1_000_000_000.0
    default_road_width: float = 24.0
    max_review_roads: int = 8
    road_confidence_distance_factor: float = 4.0
    use_hatch_priority: bool = True
    dedupe_buildings: bool = True
    filter_coordinate_clusters: bool = True
    filter_outside_roads: bool = True


STRICT_DWG_PROFILE = DWGProfile(
    mode="strict",
    label="严格审查模式",
    description="强过滤小构件、重复轮廓和内部碎线，优先输出可审查的主要对象。",
    building_hatch_layers=("G-FRIE-FLWL",),
    min_building_area=20_000_000.0,
    max_building_area=800_000_000.0,
    max_review_roads=4,
    road_confidence_distance_factor=3.0,
    use_hatch_priority=True,
    dedupe_buildings=True,
    filter_coordinate_clusters=True,
    filter_outside_roads=True,
)

BALANCED_DWG_PROFILE = DWGProfile()

RAW_DWG_PROFILE = DWGProfile(
    mode="raw",
    label="完整解析模式",
    description="尽量保留建筑轮廓和道路候选对象，但不把绿化/铺装/图案填充当作建筑，适合检查 DWG 转换结果。",
    building_insert_layers=("G-BLDG-OTLN",),
    building_polyline_layers=("G-BLDG-HIGH", "G-BLDG-MULT", "G-BLDG-OTLN"),
    building_hatch_layers=("G-FRIE-FLWL",),
    min_building_area=8_000_000.0,
    max_building_area=1_200_000_000.0,
    max_review_roads=999,
    road_confidence_distance_factor=8.0,
    use_hatch_priority=False,
    dedupe_buildings=True,
    filter_coordinate_clusters=True,
    filter_outside_roads=False,
)

DWG_PROFILES = {
    "strict": STRICT_DWG_PROFILE,
    "balanced": BALANCED_DWG_PROFILE,
    "raw": RAW_DWG_PROFILE,
}

DEFAULT_DWG_PROFILE = BALANCED_DWG_PROFILE


def get_dwg_profile(mode: str | None) -> DWGProfile:
    return DWG_PROFILES.get((mode or "balanced").lower(), DEFAULT_DWG_PROFILE)
