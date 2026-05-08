from __future__ import annotations

import re
from math import cos, radians, sin
from pathlib import Path

import ezdxf
from shapely.affinity import affine_transform, scale
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from app.dwg_profile import DEFAULT_DWG_PROFILE, DWGProfile
from app.geometry import make_linestring, make_polygon
from app.models import Building, DrawingData, Road
from app.parser import _building_type, _collect_building_text, _collect_road_text, _nearest_text, _road_text_for_centerline

# CENTER_LAYER_KEYWORDS: 判断道路图层是否属于中心线的关键词。
CENTER_LAYER_KEYWORDS = ("CENTER", "CNTR", "中心")
# DWG_UNIT_SCALE: 真实 DWG 常以毫米为图纸单位，输出审查距离时乘以 0.001 换算为米。
DWG_UNIT_SCALE = 0.001
# SCENARIO_SITE_PROP: 第二组输出，使用 G-SITE-PROP 和“总图-征地红线”作为核心红线。
SCENARIO_SITE_PROP = "site_prop_redline"
# SCENARIO_BUILDING_SITE_OPEN: 第三组输出，叠加高层/多层建筑、屋顶建筑外轮廓、用地红线和开放空间边界作为核心红线。
SCENARIO_BUILDING_SITE_OPEN = "building_site_open_redline"


def _entity_points(entity) -> list[tuple[float, float]]:
    """提取 DWG 转换 DXF 后常见线性图元的二维坐标点。

    支持 LWPOLYLINE 和 LINE；ARC 等曲线暂不直接离散化，避免引入过多误差。
    """

    etype = entity.dxftype()
    if etype == "LWPOLYLINE":
        return [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
    if etype == "LINE":
        return [(float(entity.dxf.start.x), float(entity.dxf.start.y)), (float(entity.dxf.end.x), float(entity.dxf.end.y))]
    return []


def _polyline_or_line(entity):
    """把 CAD 图元转成 Shapely 的 Polygon 或 LineString。

    闭合 LWPOLYLINE 转为 Polygon；非闭合多段线和 LINE 转为 LineString。
    """

    points = _entity_points(entity)
    if len(points) < 2:
        return None
    if entity.dxftype() == "LWPOLYLINE" and getattr(entity, "closed", False) and len(points) >= 3:
        return make_polygon(points)
    return make_linestring(points)


def _is_ignored_layer(layer: str, profile: DWGProfile) -> bool:
    """判断图层是否属于文字、标注、绿化、填充等非审查对象。"""

    upper = layer.upper()
    if upper in {item.upper() for item in profile.ignore_layers}:
        return True
    if any(keyword.upper() in upper for keyword in profile.annotation_keywords):
        return True
    return any(upper.startswith(prefix.upper()) for prefix in profile.ignore_layer_prefixes)


def _is_road_boundary_layer(layer: str, profile: DWGProfile) -> bool:
    """判断图层是否是普通道路红线/道路边界图层。"""

    if _is_ignored_layer(layer, profile):
        return False
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.road_boundary_layer_keywords)


def _is_road_centerline_layer(layer: str, profile: DWGProfile) -> bool:
    """判断图层是否是道路中心线图层。"""

    if _is_ignored_layer(layer, profile):
        return False
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.road_centerline_layer_keywords) or _is_center_layer(layer)


def _is_redline_layer(layer: str, profile: DWGProfile) -> bool:
    """判断图层是否是红线/权属控制线图层。"""

    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.redline_layer_keywords)


def _is_municipal_boundary_layer(layer: str, profile: DWGProfile) -> bool:
    if _is_ignored_layer(layer, profile):
        return False
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.municipal_boundary_keywords)


def _is_viaduct_layer(layer: str, profile: DWGProfile) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.viaduct_layer_keywords)


def _is_ramp_layer(layer: str, profile: DWGProfile) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.ramp_layer_keywords)


def _is_powerline_layer(layer: str, profile: DWGProfile) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.powerline_layer_keywords)


def _is_building_insert_layer(layer: str, profile: DWGProfile) -> bool:
    return not _is_ignored_layer(layer, profile) and layer.upper() in {item.upper() for item in profile.building_insert_layers}


def _is_building_polyline_layer(layer: str, profile: DWGProfile) -> bool:
    return not _is_ignored_layer(layer, profile) and layer.upper() in {item.upper() for item in profile.building_polyline_layers}


def _is_building_hatch_layer(layer: str, profile: DWGProfile) -> bool:
    return not _is_ignored_layer(layer, profile) and layer.upper() in {item.upper() for item in profile.building_hatch_layers}


def _is_center_layer(layer: str) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in CENTER_LAYER_KEYWORDS)


def _line_orientation(line: LineString) -> str:
    minx, miny, maxx, maxy = line.bounds
    return "vertical" if (maxy - miny) >= (maxx - minx) else "horizontal"


def _long_road_lines(lines: list[LineString]) -> list[LineString]:
    if not lines:
        return []
    lengths = sorted(line.length for line in lines)
    threshold = max(lengths[int(len(lengths) * 0.75)] if len(lengths) > 4 else lengths[-1] * 0.6, 20.0)
    return [line for line in lines if line.length >= threshold]


def _parse_voltage_from_layer(layer: str) -> float:
    """从高压线图层名中提取电压等级，识别失败时按 110kV 保守处理。"""

    match = re.search(r"(500|220|110)\s*(?:KV|千伏)?", layer.upper())
    return float(match.group(1)) if match else 110.0


def _core_redline_roads(geometries: list, label: str, profile: DWGProfile) -> list[Road]:
    """把指定图层几何转换为场景化核心红线控制对象。"""

    roads: list[Road] = []
    valid = [geom.buffer(0) if isinstance(geom, Polygon) else geom for geom in geometries if geom is not None and not geom.is_empty]
    for idx, geom in enumerate(sorted(valid, key=lambda item: item.length if isinstance(item, LineString) else item.area, reverse=True)[: profile.max_review_roads], start=1):
        if isinstance(geom, Polygon):
            polygon = geom
            centerline = None
        else:
            polygon = geom.buffer(1.0 / DWG_UNIT_SCALE, cap_style="square", join_style="mitre")
            centerline = geom
        roads.append(
            Road(
                name=f"{label}{idx}",
                polygon=polygon,
                centerline=centerline,
                width=profile.default_road_width,
                source_layer=label,
                kind="road",
            )
        )
    return roads


def _width_from_parallel_boundaries(centerline: LineString, road_lines: list[LineString], profile: DWGProfile) -> float | None:
    """利用中心线两侧平行道路边界估算道路宽度。"""

    candidates = []
    for line in road_lines:
        if line.length < centerline.length * 0.25:
            continue
        distance = line.distance(centerline)
        if distance <= 0 or distance * DWG_UNIT_SCALE > 80:
            continue
        candidates.append((distance, line))
    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda item: item[0])
    width = (candidates[0][0] + candidates[1][0]) * DWG_UNIT_SCALE
    if 4 <= width <= 80:
        return width
    return None


def _build_roads(
    road_polygons: list[Polygon],
    road_lines: list[LineString],
    centerlines: list[LineString],
    road_texts,
    profile: DWGProfile,
) -> list[Road]:
    """按图层语义构造道路：道路边界优先，中心线用于命名、交叉口和宽度兜底。"""

    # roads: 最终输出的道路/线性退让控制对象。
    roads: list[Road] = []
    # used: 已经匹配过的道路文字索引，避免多条道路重复使用同一宽度标注。
    used: set[int] = set()
    if road_polygons:
        merged = unary_union([polygon.buffer(0) for polygon in road_polygons])
        geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        for idx, geom in enumerate(sorted(geoms, key=lambda item: item.area, reverse=True)[: profile.max_review_roads]):
            text = _nearest_text((geom.centroid.x, geom.centroid.y), road_texts)
            name, width = (text[0], text[1]) if text else (f"道路{idx + 1}", profile.default_road_width)
            roads.append(Road(name=name, polygon=geom, centerline=None, width=width, source_layer="DWG_ROAD_BOUNDARY_POLYGON"))
        return roads

    if centerlines:
        chosen_centers = sorted(centerlines, key=lambda line: line.length, reverse=True)[: profile.max_review_roads]
        for idx, centerline in enumerate(chosen_centers):
            text = _road_text_for_centerline(centerline, road_texts, used)
            inferred_width = _width_from_parallel_boundaries(centerline, road_lines, profile)
            width = text[1] if text else inferred_width or profile.default_road_width
            name = text[0] if text else f"道路{idx + 1}"
            roads.append(
                Road(
                    name=name,
                    polygon=centerline.buffer((width / DWG_UNIT_SCALE) / 2.0, cap_style="square", join_style="mitre"),
                    centerline=centerline,
                    width=width,
                    source_layer="DWG_ROAD_CENTERLINE_BUFFERED",
                )
            )
        return roads

    # 没有中心线时，退化为道路边界 buffer；这是只识别到 G-ROAD-市政/园区边界时的兜底。
    for idx, line in enumerate(_long_road_lines(road_lines)[: profile.max_review_roads]):
        text = _nearest_text((line.centroid.x, line.centroid.y), road_texts)
        name, width = (text[0], text[1]) if text else (f"道路{idx + 1}", profile.default_road_width)
        roads.append(
            Road(
                name=name,
                polygon=line.buffer((width / DWG_UNIT_SCALE) / 2.0, cap_style="square", join_style="mitre"),
                centerline=line,
                width=width,
                source_layer="DWG_ROAD_BOUNDARY_BUFFERED",
            )
        )
    return roads


def _insert_virtual_polygon(insert) -> Polygon:
    """DWG 转 DXF 后部分建筑以匿名块 INSERT 存在；此处只在 DWG 分支兜底使用。"""

    x, y = float(insert.dxf.insert.x), float(insert.dxf.insert.y)
    size = 18.0
    return Polygon([(x - size, y - size), (x + size, y - size), (x + size, y + size), (x - size, y + size)])


def _insert_transform(insert, polygon: Polygon) -> Polygon:
    """将块内局部坐标按 INSERT 的缩放、旋转和平移转换到模型空间。"""

    sx = float(getattr(insert.dxf, "xscale", 1.0) or 1.0)
    sy = float(getattr(insert.dxf, "yscale", 1.0) or 1.0)
    angle = radians(float(getattr(insert.dxf, "rotation", 0.0) or 0.0))
    ix, iy = float(insert.dxf.insert.x), float(insert.dxf.insert.y)
    a = sx * cos(angle)
    b = -sy * sin(angle)
    d = sx * sin(angle)
    e = sy * cos(angle)
    return affine_transform(polygon, [a, b, d, e, ix, iy])


def _block_polygons(doc, insert) -> list[Polygon]:
    """从 INSERT 引用的块定义中提取建筑多边形，并转换到模型空间。"""

    try:
        block = doc.blocks[insert.dxf.name]
    except Exception:
        return []
    polygons: list[Polygon] = []
    for entity in block:
        if entity.dxftype() != "LWPOLYLINE":
            continue
        points = _entity_points(entity)
        if len(points) >= 3:
            polygon = make_polygon(points)
            if polygon.area > 1:
                polygons.append(_insert_transform(insert, polygon))
    return polygons


def _coord_cluster_filter(candidates: list[tuple[Polygon, str]], cell_size: float = 1_000_000.0) -> list[tuple[Polygon, str]]:
    """过滤明显跨坐标系离群对象，但保留同一总平图中的多个建筑组团。

    真实总平图常包含南北两个或多个组团，不能只保留数量最多的一簇；这里只在
    出现局部坐标和世界坐标混杂时，剔除极少数离群簇。
    """

    if not candidates:
        return []
    buckets: dict[tuple[int, int], list[tuple[Polygon, str]]] = {}
    for polygon, layer in candidates:
        key = (int(polygon.centroid.x // cell_size), int(polygon.centroid.y // cell_size))
        buckets.setdefault(key, []).append((polygon, layer))
    largest_size = max(len(items) for items in buckets.values())
    kept: list[tuple[Polygon, str]] = []
    for items in buckets.values():
        if len(items) >= 2 or len(items) >= largest_size * 0.25:
            kept.extend(items)
    return kept or candidates


def _quadrant_boxes(geometries: list) -> list[Polygon]:
    """将真实 DWG 大图按总范围等分为四个象限。"""

    valid = [geom for geom in geometries if geom is not None and not geom.is_empty]
    if not valid:
        return []
    minx, miny, maxx, maxy = unary_union(valid).bounds
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0
    return [
        box(minx, miny, midx, midy),
        box(midx, miny, maxx, midy),
        box(minx, midy, midx, maxy),
        box(midx, midy, maxx, maxy),
    ]


def _split_candidates_by_quadrant(candidates: list[tuple[Polygon, str]]) -> list[list[tuple[Polygon, str]]]:
    """把建筑候选按四象限分组，供完整模式分片去重。"""

    boxes = _quadrant_boxes([polygon for polygon, _layer in candidates])
    if not boxes:
        return [candidates]
    grouped: list[list[tuple[Polygon, str]]] = [[] for _ in boxes]
    for polygon, layer in candidates:
        point = polygon.representative_point()
        assigned = False
        for idx, quadrant in enumerate(boxes):
            if quadrant.contains(point) or quadrant.touches(point):
                grouped[idx].append((polygon, layer))
                assigned = True
                break
        if not assigned:
            grouped[0].append((polygon, layer))
    return [items for items in grouped if items]


def _split_lines_by_quadrant(lines: list[LineString]) -> list[LineString]:
    """完整模式下按四象限分别选择长道路线，再合并去重。"""

    boxes = _quadrant_boxes(lines)
    if not boxes:
        return lines
    selected: list[LineString] = []
    for quadrant in boxes:
        local = [line for line in lines if line.intersects(quadrant)]
        if not local:
            continue
        lengths = sorted(line.length for line in local)
        threshold = max(lengths[int(len(lengths) * 0.6)] if len(lengths) > 4 else lengths[0], 20.0)
        selected.extend([line for line in local if line.length >= threshold])
    unique: list[LineString] = []
    seen: set[tuple[float, float, float, float]] = set()
    for line in selected:
        key = tuple(round(value, 3) for value in line.bounds)
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
    return unique


def _dedupe_nested_buildings(candidates: list[tuple[Polygon, str]]) -> list[tuple[Polygon, str]]:
    """去掉同一建筑的内外重复轮廓，优先保留外轮廓。"""

    ordered = sorted(candidates, key=lambda item: item[0].area, reverse=True)
    kept: list[tuple[Polygon, str]] = []
    for polygon, layer in ordered:
        duplicate = False
        for kept_polygon, _kept_layer in kept:
            if polygon.centroid.distance(kept_polygon.centroid) < 8_000 and polygon.area / kept_polygon.area > 0.25:
                duplicate = True
                break
            if polygon.within(kept_polygon.buffer(1_500)) and polygon.area / kept_polygon.area > 0.2:
                duplicate = True
                break
        if not duplicate:
            kept.append((polygon, layer))
    return sorted(kept, key=lambda item: (item[0].centroid.y, item[0].centroid.x), reverse=True)


def _merge_large_roof_buildings(candidates: list[tuple[Polygon, str]], profile: DWGProfile) -> list[tuple[Polygon, str]]:
    """用屋顶外轮廓补齐大建筑，避免第二组漏掉大体量建筑。"""

    roof_layers = {"G-BLDG-ROOF", "G-BLOG-ROOF"}
    body = [(polygon, layer) for polygon, layer in candidates if layer.upper() not in roof_layers]
    roofs = [(polygon, layer) for polygon, layer in candidates if layer.upper() in roof_layers]
    kept = list(body)
    for roof_polygon, roof_layer in sorted(roofs, key=lambda item: item[0].area, reverse=True):
        if roof_polygon.area < profile.min_building_area or roof_polygon.area > profile.max_building_area:
            continue
        overlaps_body = any(
            roof_polygon.intersects(body_polygon.buffer(3_000)) and min(roof_polygon.area, body_polygon.area) / max(roof_polygon.area, body_polygon.area) > 0.03
            for body_polygon, _body_layer in body
        )
        contains_body = any(roof_polygon.buffer(2_000).contains(body_polygon.representative_point()) for body_polygon, _body_layer in body)
        if not overlaps_body or contains_body:
            kept.append((roof_polygon, roof_layer))
    return kept


def _hatch_polygons(entity) -> list[Polygon]:
    """从 HATCH 边界中提取多边形候选。"""

    polygons: list[Polygon] = []
    for path in entity.paths:
        vertices = []
        try:
            vertices = [(float(point[0]), float(point[1])) for point in path.vertices]
        except Exception:
            vertices = []
        if len(vertices) >= 3:
            polygon = make_polygon(vertices)
            if polygon.area > 1:
                polygons.append(polygon)
    return polygons


def _resolve_building_text(polygon: Polygon, building_texts):
    """优先用落在建筑内/邻近建筑的文字，避免大建筑被远处文字错配。"""

    inside = [text for text in building_texts if polygon.buffer(1_500).contains(Point(text[2][0], text[2][1]))]
    if inside:
        return min(inside, key=lambda item: polygon.centroid.distance(Point(item[2][0], item[2][1])))
    near = [text for text in building_texts if polygon.distance(Point(text[2][0], text[2][1])) <= 8_000]
    if near:
        return min(near, key=lambda item: polygon.centroid.distance(Point(item[2][0], item[2][1])))
    return _nearest_text((polygon.centroid.x, polygon.centroid.y), building_texts)


def _building_floor_height_from_layer(layer: str, text_height: float, text_floors: int) -> tuple[int, float]:
    """根据图层语义和文字结果补齐楼层/高度。"""

    upper = layer.upper()
    floors = text_floors
    height = text_height
    if floors <= 0:
        if "HIGH" in upper:
            floors = 18
        elif "MULT" in upper:
            floors = 6
        elif "ROOF" in upper or "OTLN" in upper:
            floors = 6
    if height <= 0 and floors > 0:
        height = floors * 3.0
    if height <= 0:
        height = 54.0 if "HIGH" in upper else 18.0
    return floors, height


def _build_buildings(doc, modelspace, building_texts, profile: DWGProfile) -> list[Building]:
    """根据 DWGProfile 中的建筑图层配置提取建筑对象。"""

    # hatch_candidates: HATCH 面域候选，默认关闭，只在 profile 指定时启用。
    hatch_candidates: list[tuple[Polygon, str]] = []
    # candidates: 普通建筑轮廓候选，元素为 (建筑多边形, 来源图层)。
    candidates: list[tuple[Polygon, str]] = []
    candidates: list[tuple[Polygon, str]] = []
    for entity in modelspace:
        layer = entity.dxf.layer
        etype = entity.dxftype()
        if etype == "HATCH" and _is_building_hatch_layer(layer, profile):
            for polygon in _hatch_polygons(entity):
                if profile.min_building_area <= polygon.area <= profile.max_building_area:
                    hatch_candidates.append((polygon, layer))
            continue
        if etype == "INSERT" and _is_building_insert_layer(layer, profile):
            block_polys = _block_polygons(doc, entity)
            for polygon in block_polys or [_insert_virtual_polygon(entity)]:
                candidates.append((polygon, layer))
            continue
        if etype == "LWPOLYLINE" and _is_building_polyline_layer(layer, profile):
            points = _entity_points(entity)
            if len(points) >= 3:
                polygon = make_polygon(points)
                if profile.min_building_area <= polygon.area <= profile.max_building_area:
                    candidates.append((polygon, layer))

    buildings: list[Building] = []
    if hatch_candidates:
        hatch_union = unary_union([polygon for polygon, _layer in hatch_candidates])
        overlapped = [(polygon, layer) for polygon, layer in candidates if polygon.intersects(hatch_union.buffer(2_000))]
        if profile.use_hatch_priority:
            # 严格/平衡模式下，填充面作为建筑语义增强，但仍保留与填充重叠的轮廓。
            candidates = hatch_candidates + (overlapped or candidates)
        else:
            # 完整模式不做语义裁剪，全部候选保留。
            candidates = candidates + hatch_candidates
    if not candidates:
        return []
    candidates = _merge_large_roof_buildings(candidates, profile)

    if profile.split_quadrants:
        merged: list[tuple[Polygon, str]] = []
        for group in _split_candidates_by_quadrant(candidates):
            if profile.filter_coordinate_clusters:
                group = _coord_cluster_filter(group)
            if profile.dedupe_buildings:
                group = _dedupe_nested_buildings(group)
            merged.extend(group)
        candidates = _dedupe_nested_buildings(merged) if profile.dedupe_buildings else merged
    else:
        if profile.filter_coordinate_clusters:
            candidates = _coord_cluster_filter(candidates)
        if profile.dedupe_buildings:
            candidates = _dedupe_nested_buildings(candidates)

    # 最后再做一次面积过滤，避免分片/合并过程中混入过小或过大的轮廓。
    candidates = [(polygon, layer) for polygon, layer in candidates if profile.min_building_area <= polygon.area <= profile.max_building_area]

    for idx, (polygon, layer) in enumerate(candidates, start=1):
        nearest = _resolve_building_text(polygon, building_texts)
        text_height = float(nearest[1] if nearest and nearest[1] is not None else 0.0)
        text_floors = int(nearest[3]) if nearest and len(nearest) > 3 and nearest[3] is not None else max(0, round(text_height / 3.0))
        floors, height = _building_floor_height_from_layer(layer, text_height, text_floors)
        inferred_name = nearest[0] if nearest and nearest[0] else None
        name = str(inferred_name) if inferred_name else f"B{idx}"
        buildings.append(
            Building(
                name=name,
                polygon=polygon,
                height=height,
                btype=_building_type(layer, name, height),
                layer=layer,
                floors=floors,
            )
        )
    return buildings


def parse_converted_dwg_dxf(path: str | Path, profile: DWGProfile = DEFAULT_DWG_PROFILE) -> DrawingData:
    """DWG 转换 DXF 专用解析器。

    与简化 DXF 的图层约定完全隔离，面向真实 DWG 转换后的常见图层：G-ROAD、
    G-BLDG、INSERT 匿名块、LINE/ARC 混合图元等。当前策略偏保守，优先保证
    原 DXF 分支不被影响。
    """

    # doc / msp: DWG 经 ODA 转换后的 DXF 文档和模型空间。
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    # road_texts: 道路名称和宽度文字，复用标准 DXF 解析器的文字提取逻辑。
    road_texts = _collect_road_text(msp)
    # building_texts: 建筑高度和名称文字，后续按最近邻匹配建筑轮廓。
    building_texts = _collect_building_text(msp)
    # road_polygons: 闭合道路面域候选。
    road_polygons: list[Polygon] = []
    # road_lines: 非中心线的道路边线候选。
    road_lines: list[LineString] = []
    # redline_geoms: 红线/权属控制边界候选，仅用于辅助筛选道路。
    redline_geoms = []
    # special_lines: 高架、匝道、高压线等加分项线性设施。
    special_lines: list[tuple[LineString, str, str, float]] = []
    # centerlines: 道路中心线候选。
    centerlines: list[LineString] = []
    # scenario_site_prop_geoms: 第二组场景专用核心红线几何。
    scenario_site_prop_geoms: list = []
    # scenario_open_space_geoms: 第三组场景额外加入的开放空间边界几何。
    scenario_open_space_geoms: list = []
    # scenario_building_geoms: 第三组场景纳入核心红线的高层/多层建筑轮廓。
    scenario_building_geoms: list[Polygon] = []
    warnings: list[str] = [
        f"DWG 专用解析模式：{profile.label}。{profile.description}",
        "DWG 坐标按毫米级总图坐标处理，审查距离输出时按 0.001 换算为米。",
        "完整解析模式会将大图按空间范围等分为四个象限，分别解析候选对象后再合并，降低大图尺度差异带来的误判。" if profile.split_quadrants else "当前模式按全图统一解析候选对象。",
        "已按图层语义过滤 DIM/TEXT/AXIS 标注层、A_N/G_N 注释层、绿化/铺装/停车等非审查对象。",
        "普通道路优先来自 G-ROAD-市政、G-ROAD-园区、G_DRIV_ROAD；道路中心线优先来自 G-ROAD-CNTR；G-SITE-PROP、G_SITE_REDL、总图-征地红线只作为核心红线场景，不混入普通道路退距计算。",
        "建筑主体优先识别 G-BLDG-HIGH、G-BLDG-MULT、G-BLDG-OTLN，并可用 G-BLDG-ROOF / G-BLOG-ROOF 补齐大建筑外轮廓。",
        "审查规则包含题目核心表3-2、第3款，并支持可选加分项表3-3高架/匝道和表3-4高压线退让。",
    ]

    for entity in msp:
        # DWG 转换后的真实图纸中图元类型很多；这里仅处理能稳定转线/面的 LINE 和 LWPOLYLINE。
        if entity.dxftype() not in {"LWPOLYLINE", "LINE"}:
            continue
        layer = entity.dxf.layer
        geom = _polyline_or_line(entity)
        if geom is None:
            continue
        # 加分项设施优先识别，避免被普通道路逻辑吞掉。
        if isinstance(geom, LineString) and _is_viaduct_layer(layer, profile):
            special_lines.append((geom, "viaduct", "高架", profile.default_road_width))
            continue
        if isinstance(geom, LineString) and _is_ramp_layer(layer, profile):
            special_lines.append((geom, "ramp", "匝道", profile.default_road_width))
            continue
        if isinstance(geom, LineString) and _is_powerline_layer(layer, profile):
            special_lines.append((geom, "powerline", "高压线", _parse_voltage_from_layer(layer)))
            continue
        if _is_redline_layer(layer, profile):
            redline_geoms.append(geom)
            scenario_site_prop_geoms.append(geom)
        if any(keyword.upper() in layer.upper() for keyword in profile.scenario_open_space_redline_keywords):
            scenario_open_space_geoms.append(geom)
        if entity.dxftype() == "LWPOLYLINE" and layer.upper() in {"G-BLDG-HIGH", "G-BLDG-MULT", "G-BLDG-ROOF", "G-BLOG-ROOF"} and isinstance(geom, Polygon):
            scenario_building_geoms.append(geom)
        # 普通道路候选严格按图层语义拆分：道路边界与道路中心线分开识别。
        is_road_boundary = _is_road_boundary_layer(layer, profile) or (profile.include_blue_boundary_roads and _is_municipal_boundary_layer(layer, profile))
        is_road_centerline = _is_road_centerline_layer(layer, profile)
        if is_road_centerline and isinstance(geom, LineString):
            centerlines.append(geom)
            continue
        if is_road_boundary:
            if isinstance(geom, Polygon):
                road_polygons.append(geom)
            elif isinstance(geom, LineString):
                road_lines.append(geom)

    # 道路中心线和边线筛选：完整模式按四象限分片，其他模式保留长线。
    if centerlines:
        if profile.split_quadrants:
            centerlines = _split_lines_by_quadrant(centerlines)
        else:
            centerlines = _long_road_lines(centerlines)
    if road_lines:
        road_lines = _split_lines_by_quadrant(road_lines) if profile.split_quadrants else _long_road_lines(road_lines)

    buildings = _build_buildings(doc, msp, building_texts, profile)
    # 只有在完全没有道路候选时，才允许红线兜底；正常情况下红线不直接当道路中心线。
    if profile.prefer_redline_roads and redline_geoms and not centerlines and not road_polygons and not road_lines:
        redline_lines = [geom for geom in redline_geoms if isinstance(geom, LineString)]
        if redline_lines:
            road_lines = sorted(redline_lines, key=lambda line: line.length, reverse=True)[: profile.max_review_roads]

    if redline_geoms:
        # redline_union: 红线合并几何，用来过滤离红线过远的道路碎线。
        redline_union = unary_union(redline_geoms)
        if centerlines:
            centerlines = [line for line in centerlines if line.distance(redline_union) <= profile.redline_near_road_distance]
        if road_lines:
            road_lines = [line for line in road_lines if line.distance(redline_union) <= profile.redline_near_road_distance]

    if profile.filter_outside_roads and buildings:
        building_union = unary_union([building.polygon for building in buildings])
        outside_centers = [line for line in centerlines if not line.intersects(building_union.buffer(500))]
        outside_lines = [line for line in road_lines if not line.intersects(building_union.buffer(500))]
        centerlines = outside_centers or centerlines
        road_lines = outside_lines or road_lines

    # roads: 普通道路对象，按“道路面域 > 中心线 > 边线 buffer”的优先级构造。
    roads = _build_roads(road_polygons, road_lines, centerlines, road_texts, profile)
    scenario_core_redlines = {
        SCENARIO_SITE_PROP: _core_redline_roads(scenario_site_prop_geoms, "用地/征地红线", profile),
        SCENARIO_BUILDING_SITE_OPEN: _core_redline_roads(
            scenario_building_geoms + scenario_site_prop_geoms + scenario_open_space_geoms,
            "建筑-用地-开放核心红线",
            profile,
        ),
    }
    site_prop_buildings = _build_buildings(doc, msp, building_texts, profile)
    scenario_buildings = {
        SCENARIO_SITE_PROP: site_prop_buildings,
        SCENARIO_BUILDING_SITE_OPEN: buildings,
    }
    for idx, (line, kind, label, width) in enumerate(special_lines, start=1):
        roads.append(
            Road(
                name=f"{label}{idx}",
                polygon=line.buffer((profile.default_road_width / DWG_UNIT_SCALE) / 2.0 if kind != "powerline" else 1.0 / DWG_UNIT_SCALE, cap_style="square", join_style="mitre"),
                centerline=line,
                width=width,
                source_layer=f"DWG_SPECIAL_{kind.upper()}",
                kind=kind,
            )
        )
    # confidence: 对解析质量的粗略判断，报告中用于提示是否需要人工复核。
    confidence = "high"
    if not buildings:
        confidence = "low"
        warnings.append("未识别到建筑轮廓，无法形成有效逐栋审查。")
    if not roads:
        confidence = "low"
        warnings.append("未识别到道路红线/道路中心线，无法形成有效退让审查。")
    elif buildings:
        building_union = unary_union([building.polygon for building in buildings])
        nearest_road_distance = min((road.polygon.distance(building_union) for road in roads), default=float("inf"))
        typical_width = max((road.width for road in roads), default=profile.default_road_width)
        if nearest_road_distance > typical_width * profile.road_confidence_distance_factor:
            confidence = "low"
            warnings.append(
                f"道路候选与建筑组团最近距离约 {nearest_road_distance:.1f}，明显大于道路宽度，"
                "道路红线识别置信度低，审查结论需人工复核。"
            )
    if redline_geoms and confidence == "low":
        warnings.append("检测到红线/边界类图层，但尚未能稳定构造道路红线面域，已保守标记为低置信度。")
    return DrawingData(
        roads=roads,
        buildings=buildings,
        scenario_core_redlines=scenario_core_redlines,
        scenario_buildings=scenario_buildings,
        parse_warnings=warnings,
        parse_mode="dwg-profile",
        confidence=confidence,
        unit_scale=DWG_UNIT_SCALE,
    )
