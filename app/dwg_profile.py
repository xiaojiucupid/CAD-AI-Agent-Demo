from __future__ import annotations

from dataclasses import dataclass


# 本文件是 DWG 解析最重要的“可调配置入口”。
# 真实 DWG 图层复杂且项目差异很大，因此不要把所有判断写死在解析算法里，
# 而是通过 DWGProfile 把图层映射为：建筑、道路、红线、忽略层、加分项设施。


@dataclass(frozen=True)
class DWGProfile:
    """DWG 精确图层角色配置。

    mode: 模式名称，strict/balanced/raw。
    label: 展示在 Web 页面和报告中的中文模式名。
    description: 展示在报告中的模式说明。
    """

    mode: str = "balanced"
    label: str = "平衡识别模式"
    description: str = "按用户提供图层语义精确识别建筑主体、道路系统和红线控制线。"

    # building_insert_layers: 建筑以块参照 INSERT 存在时，允许解析的图层。
    building_insert_layers: tuple[str, ...] = ("G-BLDG-OTLN",)
    # building_polyline_layers: 建筑以 LWPOLYLINE 轮廓存在时，允许解析的图层。
    # G-BLDG-POIT 是定位点/转折点，不作为面域建筑；G-FRIE-FLWL 是防火分区线，不作为建筑。
    # G-BLDG-ROOF / G-BLOG-ROOF 在当前测试图中包围的是建筑屋顶外轮廓，纳入可补齐部分大建筑。
    building_polyline_layers: tuple[str, ...] = ("G-BLDG-HIGH", "G-BLDG-MULT", "G-BLDG-EXTG", "G-BLDG-OTLN", "G-BLDG-ROOF", "G-BLOG-ROOF")
    # building_hatch_layers: 建筑以 HATCH 面填充存在时，允许解析的图层；当前默认关闭，避免把铺装/绿化填充误判为建筑。
    building_hatch_layers: tuple[str, ...] = ()

    # road_boundary_layer_keywords: 普通道路红线/边界图层关键词。
    # 本题优先使用 G-ROAD-市政、G-ROAD-园区 作为道路红线直接来源。
    road_boundary_layer_keywords: tuple[str, ...] = ("G-ROAD-市政", "G-ROAD-园区", "G_DRIV_ROAD")
    # road_centerline_layer_keywords: 道路中心线图层关键词。
    # 优先使用 G-ROAD-CNTR 识别道路中心线，用于交叉口判断和宽度缓冲兜底。
    road_centerline_layer_keywords: tuple[str, ...] = ("G-ROAD-CNTR",)
    # redline_layer_keywords: 红线/控制线图层关键词。默认只进入场景化核心红线，不混入普通道路退距计算。
    redline_layer_keywords: tuple[str, ...] = ("G-SITE-PROP", "G_SITE_REDL", "总图-征地红线")
    # scenario_open_space_redline_keywords: 第三组场景补充纳入核心红线的开放空间边界图层。
    scenario_open_space_redline_keywords: tuple[str, ...] = ("G-SITE-开放",)
    # municipal_boundary_keywords: 市政道路边界关键词，作为道路候选的补充入口。
    municipal_boundary_keywords: tuple[str, ...] = ("G-ROAD-市政",)

    # viaduct_layer_keywords: 表 3-3 高架候选图层关键词。
    viaduct_layer_keywords: tuple[str, ...] = ("高架", "VIADUCT", "ELEVATED")
    # ramp_layer_keywords: 表 3-3 匝道候选图层关键词。
    ramp_layer_keywords: tuple[str, ...] = ("匝道", "RAMP")
    # powerline_layer_keywords: 表 3-4 高压线候选图层关键词。
    powerline_layer_keywords: tuple[str, ...] = ("高压", "电力", "POWER", "ELECTRIC", "HV")

    # annotation_keywords: 只要图层名包含这些关键词，就认为是标注/文字/轴网类，不参与几何审查对象提取。
    annotation_keywords: tuple[str, ...] = ("_N_", "_DIM", "DIM_", "TEXT", "TEX", "AXIS", "ANNO", "PUB_DIM", "PUB_TEXT")
    # ignore_layer_prefixes: 以前缀形式忽略整类图层。
    ignore_layer_prefixes: tuple[str, ...] = ("A_N_", "G_N_", "DIM_", "PUB_DIM", "PUB_TEXT", "AXIS", "Defpoints")
    # ignore_layers: 明确忽略的图层名，主要是绿化、填充、停车、地下、楼梯、文字等非审查对象。
    ignore_layers: tuple[str, ...] = (
        "PROMPT",
        "A_N_DIM_ELEV",
        "A_N_DIM_LEAD",
        "A_N_DIM_SYMB",
        "DIM_COOR",
        "G-ANNO-DIMS",
        "G_N_DIM_SYMB",
        "G_N_FIGURE",
        "G_N_GUIDES",
        "PUB_DIM",
        "A_N_AXIS",
        "A_SITEP_PLANT",
        "G-ANNO-GRID",
        "G-PATT-251",
        "G-PLTG",
        "G-SITE-GREN",
        "A_STAIR",
        "G-SITE-BLUE",
        "G-STRU",
        "G-BLDG-POIT",
        "G-FRIE-FLWL",
        "G-设施-EXTG",
        "0",
        "AXIS_TEXT",
        "A_N_AXIS_TEXT",
        "A_N_PUB_TEXT",
        "A_N_RMNAME",
        "A_SITEP_TEX_1",
        "A_SITEP_TEX_2",
        "C-ICON",
        "Defpoints",
        "G-ANNO-TEXT",
        "G_N_PUB_TEXT",
        "PUB_TEXT",
        "iicon",
        "G-PARG",
        "G-SDWK",
        "G-TERN",
        "G_H_252",
        "G_H_253",
        "PUB_HATCH",
        "PUB_WALL",
        "总图-地面填充",
        "G-BSMT-OTLN",
        "A_ABOVE",
        "A_N_AREA",
        "A_CUR_GLAZE",
        "G_N_TEXT",
        "0停车位",
        "A_OTHER_MEMBER",
        "A_PLAN_DETAIL_2",
        "A_ROOF_2",
        "G-ANNO-LEGN",
        "G-ANNO-TABL",
        "G-OTHR",
        "G-SITE-开放",
    )

    # min_building_area: 建筑最小面积阈值，DWG 常为毫米坐标，所以面积单位是图纸单位平方。
    min_building_area: float = 5_000_000.0
    # max_building_area: 建筑最大面积阈值，避免把用地边界或大片铺装误判为建筑。
    max_building_area: float = 1_000_000_000.0
    # default_road_width: 道路文字缺失时使用的默认道路红线宽度，单位米。
    default_road_width: float = 24.0
    # max_review_roads: 最多进入审查的道路候选数量，防止真实 DWG 道路碎线过多导致报告膨胀。
    max_review_roads: int = 12
    # road_confidence_distance_factor: 道路与建筑组团距离过远时的低置信度判断倍数。
    road_confidence_distance_factor: float = 8.0
    # use_hatch_priority: 是否优先使用 HATCH 面作为建筑语义增强。
    use_hatch_priority: bool = False
    # dedupe_buildings: 是否对同一建筑的内外重复轮廓去重。
    dedupe_buildings: bool = True
    # filter_coordinate_clusters: 是否过滤明显跨坐标系的离群对象。
    filter_coordinate_clusters: bool = True
    # filter_outside_roads: 是否过滤穿越建筑组团的内部道路碎线。
    filter_outside_roads: bool = False
    # prefer_redline_roads: 无道路候选时是否允许用红线兜底构造道路。
    prefer_redline_roads: bool = False
    # include_blue_boundary_roads: 是否把市政边界类图层额外作为道路候选。
    include_blue_boundary_roads: bool = False
    # split_quadrants: 是否把大图切成四象限分别筛选候选，再合并。
    split_quadrants: bool = False
    # redline_near_road_distance: 有红线时，道路候选距离红线超过该阈值则过滤。
    redline_near_road_distance: float = 50_000.0


# 严格模式：用于最终报告，宁可少识别，也要尽量减少错误道路和错误建筑。
STRICT_DWG_PROFILE = DWGProfile(
    mode="strict",
    label="严格审查模式",
    description="按题目图层语义识别：G-ROAD-市政/园区 为道路边界，G-ROAD-CNTR 为道路中心线，建筑取 G-BLDG-HIGH/MULT/OTLN/ROOF。",
    max_review_roads=8,
    min_building_area=8_000_000.0,
)

# 平衡模式：默认模式，在对象覆盖率和误识别之间取中。
BALANCED_DWG_PROFILE = DWGProfile()

# 完整模式：用于排查解析覆盖情况；会保留更多候选，并启用四象限分片。
RAW_DWG_PROFILE = DWGProfile(
    mode="raw",
    label="完整解析模式",
    description="按四象限分片解析后合并，但仍严格限于用户表中的建筑主体层和道路专用层。",
    max_review_roads=80,
    split_quadrants=True,
    min_building_area=3_000_000.0,
)

# DWG_PROFILES: Web 和 CLI 根据模式字符串选择具体配置。
DWG_PROFILES = {
    "strict": STRICT_DWG_PROFILE,
    "balanced": BALANCED_DWG_PROFILE,
    "raw": RAW_DWG_PROFILE,
}

# DEFAULT_DWG_PROFILE: 用户未指定时采用平衡模式。
DEFAULT_DWG_PROFILE = BALANCED_DWG_PROFILE


def get_dwg_profile(mode: str | None) -> DWGProfile:
    """根据模式名称返回 DWG 解析配置。

    mode: strict / balanced / raw，大小写不敏感；未知值回退到默认配置。
    """

    return DWG_PROFILES.get((mode or "balanced").lower(), DEFAULT_DWG_PROFILE)
