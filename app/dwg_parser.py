from __future__ import annotations

import re
from math import cos, radians, sin
from pathlib import Path

import ezdxf
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union

from app.dwg_profile import DEFAULT_DWG_PROFILE, DWGProfile
from app.geometry import make_linestring, make_polygon
from app.models import Building, DrawingData, Road
from app.parser import _building_type, _collect_building_text, _collect_road_text, _nearest_text, _road_text_for_centerline

CENTER_LAYER_KEYWORDS = ("CENTER", "CNTR", "中心")


def _entity_points(entity) -> list[tuple[float, float]]:
    etype = entity.dxftype()
    if etype == "LWPOLYLINE":
        return [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
    if etype == "LINE":
        return [(float(entity.dxf.start.x), float(entity.dxf.start.y)), (float(entity.dxf.end.x), float(entity.dxf.end.y))]
    return []


def _polyline_or_line(entity):
    points = _entity_points(entity)
    if len(points) < 2:
        return None
    if entity.dxftype() == "LWPOLYLINE" and getattr(entity, "closed", False) and len(points) >= 3:
        return make_polygon(points)
    return make_linestring(points)


def _is_road_layer(layer: str, profile: DWGProfile) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.road_layer_keywords)


def _is_redline_layer(layer: str, profile: DWGProfile) -> bool:
    upper = layer.upper()
    return any(keyword.upper() in upper for keyword in profile.redline_layer_keywords)


def _is_building_insert_layer(layer: str, profile: DWGProfile) -> bool:
    return layer.upper() in {item.upper() for item in profile.building_insert_layers}


def _is_building_polyline_layer(layer: str, profile: DWGProfile) -> bool:
    return layer.upper() in {item.upper() for item in profile.building_polyline_layers}


def _is_building_hatch_layer(layer: str, profile: DWGProfile) -> bool:
    return layer.upper() in {item.upper() for item in profile.building_hatch_layers}


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


def _build_roads(road_geoms: list, centerlines: list[LineString], road_texts, profile: DWGProfile) -> list[Road]:
    roads: list[Road] = []
    used: set[int] = set()
    source_lines = centerlines or _long_road_lines([geom for geom in road_geoms if isinstance(geom, LineString)])
    chosen_centers = sorted(source_lines, key=lambda line: line.length, reverse=True)[: profile.max_review_roads]

    for idx, centerline in enumerate(chosen_centers):
        text = _road_text_for_centerline(centerline, road_texts, used)
        name, width = (text[0], text[1]) if text else (f"道路{idx + 1}", profile.default_road_width)
        roads.append(
            Road(
                name=name,
                polygon=centerline.buffer(width / 2.0, cap_style="square", join_style="mitre"),
                centerline=centerline,
                width=width,
                source_layer="DWG_CONVERTED_ROAD_CENTER",
            )
        )

    if roads:
        return roads

    polygons = [geom for geom in road_geoms if isinstance(geom, Polygon) and geom.area > 1]
    if polygons:
        merged = unary_union(polygons)
        geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        for idx, geom in enumerate(geoms):
            text = _nearest_text((geom.centroid.x, geom.centroid.y), road_texts)
            name, width = (text[0], text[1]) if text else (f"道路{idx + 1}", profile.default_road_width)
            roads.append(Road(name=name, polygon=geom, centerline=None, width=width, source_layer="DWG_CONVERTED_ROAD_POLYGON"))
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


def _hatch_polygons(entity) -> list[Polygon]:
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


def _build_buildings(doc, modelspace, building_texts, profile: DWGProfile) -> list[Building]:
    hatch_candidates: list[tuple[Polygon, str]] = []
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
    if profile.filter_coordinate_clusters:
        candidates = _coord_cluster_filter(candidates)
    if profile.dedupe_buildings:
        candidates = _dedupe_nested_buildings(candidates)

    candidates = [(polygon, layer) for polygon, layer in candidates if profile.min_building_area <= polygon.area <= profile.max_building_area]

    for idx, (polygon, layer) in enumerate(candidates, start=1):
        nearest = _nearest_text((polygon.centroid.x, polygon.centroid.y), building_texts)
        height = float(nearest[1] if nearest and nearest[1] is not None else 0.0)
        name = f"B{idx}"
        buildings.append(
            Building(
                name=name,
                polygon=polygon,
                height=height,
                btype=_building_type(layer, name, height),
                layer=layer,
            )
        )
    return buildings


def parse_converted_dwg_dxf(path: str | Path, profile: DWGProfile = DEFAULT_DWG_PROFILE) -> DrawingData:
    """DWG 转换 DXF 专用解析器。

    与简化 DXF 的图层约定完全隔离，面向真实 DWG 转换后的常见图层：G-ROAD、
    G-BLDG、INSERT 匿名块、LINE/ARC 混合图元等。当前策略偏保守，优先保证
    原 DXF 分支不被影响。
    """

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    road_texts = _collect_road_text(msp)
    building_texts = _collect_building_text(msp)
    road_geoms = []
    redline_geoms = []
    centerlines: list[LineString] = []
    warnings: list[str] = [
        f"DWG 专用解析模式：{profile.label}。{profile.description}",
        "优先使用 HATCH/填充面、块参照和建筑轮廓图层识别建筑候选；文字乱码时仍可基于图形审查。",
    ]

    for entity in msp:
        if entity.dxftype() not in {"LWPOLYLINE", "LINE"}:
            continue
        layer = entity.dxf.layer
        geom = _polyline_or_line(entity)
        if geom is None:
            continue
        if _is_redline_layer(layer, profile):
            redline_geoms.append(geom)
        if _is_road_layer(layer, profile):
            road_geoms.append(geom)
            if isinstance(geom, LineString) and (_is_center_layer(layer) or geom.length > 50):
                centerlines.append(geom)

    if centerlines:
        lengths = sorted(line.length for line in centerlines)
        min_center_length = max(lengths[int(len(lengths) * 0.8)], 80.0)
        centerlines = [line for line in centerlines if line.length >= min_center_length]

    buildings = _build_buildings(doc, msp, building_texts, profile)
    if profile.filter_outside_roads and buildings and centerlines:
        building_union = unary_union([building.polygon for building in buildings])
        # 主审对象是沿城市道路的建筑退让。真实图中内部园路线很多，优先保留
        # 位于建筑群外侧、不穿越建筑组团的长道路线，避免道路数量膨胀到几十条。
        outside_lines = [line for line in centerlines if not line.intersects(building_union.buffer(500))]
        if outside_lines:
            centerlines = outside_lines

    roads = _build_roads(road_geoms, centerlines, road_texts, profile)
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
        parse_warnings=warnings,
        parse_mode="dwg-profile",
        confidence=confidence,
    )
