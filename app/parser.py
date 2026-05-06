from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf
from shapely.geometry import LineString
from shapely.ops import unary_union

from app.geometry import make_linestring, make_polygon
from app.models import Building, DrawingData, Road

WIDTH_RE = re.compile(r"(?:W|宽|红线宽度)\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m|米)?", re.IGNORECASE)
ROAD_NAME_RE = re.compile(r"(道路[^:：\s]+|[^:：\s]+路|[^:：\s]+街|[^:：\s]+大道)")
HEIGHT_RE = re.compile(r"(?:H|高度|建筑高度)\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m|米)?", re.IGNORECASE)
NAME_RE = re.compile(r"(?:建筑|楼栋|楼号)\s*[=:：]?\s*([^,，;；\s]+)")


def _polyline_points(entity) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]


def _xdata_value(entity, code: int):
    try:
        for item in entity.get_xdata("HZPLAN"):
            if item.code == code:
                return item.value
    except Exception:
        return None
    return None


def _text_content(entity) -> str:
    """兼容读取 TEXT 与 MTEXT 内容，用于提取道路名称和宽度标注。"""

    if entity.dxftype() == "MTEXT":
        try:
            return entity.plain_text()
        except Exception:
            return getattr(entity, "text", "") or getattr(entity.dxf, "text", "")
    return getattr(entity.dxf, "text", "") or getattr(entity, "text", "")


def _text_insert_point(entity) -> tuple[float, float]:
    point = getattr(entity.dxf, "insert", None)
    if point is None:
        return (0.0, 0.0)
    return (float(point.x), float(point.y))


def _collect_road_text(modelspace) -> list[tuple[str, float, tuple[float, float], str | None]]:
    road_texts: list[tuple[str, float, tuple[float, float], str | None]] = []
    for text in modelspace.query("TEXT MTEXT"):
        raw = _text_content(text)
        width_match = WIDTH_RE.search(raw)
        name_match = ROAD_NAME_RE.search(raw)
        if width_match:
            name = name_match.group(1) if name_match else f"道路{len(road_texts) + 1}"
            road_texts.append((name, float(width_match.group(1)), _text_insert_point(text), _text_orientation_hint(raw)))
    return road_texts


def _collect_building_text(modelspace) -> list[tuple[str | None, float | None, tuple[float, float]]]:
    building_texts: list[tuple[str | None, float | None, tuple[float, float]]] = []
    for text in modelspace.query("TEXT MTEXT"):
        raw = _text_content(text)
        height_match = HEIGHT_RE.search(raw)
        name_match = NAME_RE.search(raw)
        if height_match or name_match:
            building_texts.append(
                (
                    name_match.group(1) if name_match else None,
                    float(height_match.group(1)) if height_match else None,
                    _text_insert_point(text),
                )
            )
    return building_texts


def _nearest_text(point, texts):
    if not texts:
        return None
    px, py = point
    return min(texts, key=lambda item: math.hypot(px - item[2][0], py - item[2][1]))


def _nearest_road_text_to_geometry(geometry, texts, used_indexes: set[int]):
    if not texts:
        return None
    ordered = sorted(
        enumerate(texts),
        key=lambda item: LineString([item[1][2], (geometry.centroid.x, geometry.centroid.y)]).length,
    )
    for idx, text in ordered:
        if idx not in used_indexes:
            used_indexes.add(idx)
            return text
    return ordered[0][1]


def _line_orientation(line: LineString) -> str:
    """粗略判断道路中心线方向，用于把道路文字匹配到正确道路。"""

    minx, miny, maxx, maxy = line.bounds
    return "vertical" if (maxy - miny) >= (maxx - minx) else "horizontal"


def _text_orientation_hint(raw: str) -> str | None:
    if "南北" in raw or "纵" in raw or "竖" in raw:
        return "vertical"
    if "东西" in raw or "横" in raw:
        return "horizontal"
    return None


def _road_text_for_centerline(centerline: LineString, texts, used_indexes: set[int]):
    if not texts:
        return None
    orientation = _line_orientation(centerline)
    candidates = [(idx, text) for idx, text in enumerate(texts) if idx not in used_indexes]
    hinted = [(idx, text) for idx, text in candidates if len(text) >= 4 and text[3] == orientation]
    pool = hinted or candidates
    if not pool:
        pool = list(enumerate(texts))
    idx, text = min(pool, key=lambda item: LineString([item[1][2], (centerline.centroid.x, centerline.centroid.y)]).length)
    used_indexes.add(idx)
    return text


def _building_type(layer: str, name: str, height: float) -> str:
    text = f"{layer}_{name}".upper()
    if "HIGH" in text or height >= 50:
        return "高层"
    if "MULTI" in text or height >= 10:
        return "多层"
    return "低层"


def parse_drawing(path: str | Path) -> DrawingData:
    """解析 DXF 中的道路红线与建筑轮廓。

    依赖图层命名：ROAD_REDLINE / BUILDING_LOW|MULTI|HIGH；建筑高度读取
    HZPLAN XDATA 1040 字段，建筑名称读取 HZPLAN XDATA 1000 字段。
    当前 Demo 使用 `ezdxf` 直接解析 DXF；若输入为 DWG，会提示先转 DXF。
    """

    path = Path(path)
    if path.suffix.lower() == ".dwg":
        raise ValueError(
            "检测到 DWG 输入。当前 Demo 仅直接解析 DXF，请先使用 ODA File Converter、AutoCAD 或 Teigha 将 DWG 转为 DXF 后再审查。"
        )

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    road_texts = _collect_road_text(msp)
    building_texts = _collect_building_text(msp)
    road_polys = []
    road_lines: list[LineString] = []
    buildings: list[Building] = []
    centerlines = []

    for entity in msp:
        etype = entity.dxftype()
        layer = entity.dxf.layer
        if etype != "LWPOLYLINE":
            continue
        points = _polyline_points(entity)
        if len(points) < 2:
            continue
        if layer == "ROAD_CENTERLINE":
            centerlines.append(make_linestring(points))
        elif layer == "ROAD_REDLINE":
            if len(points) >= 3 and entity.closed:
                road_polys.append(make_polygon(points))
            elif len(points) >= 2:
                road_lines.append(make_linestring(points))
        elif (layer.startswith("BUILDING") or "建筑" in layer or "楼" in layer) and len(points) >= 3:
            polygon = make_polygon(points)
            nearest = _nearest_text((polygon.centroid.x, polygon.centroid.y), building_texts)
            name = _xdata_value(entity, 1000) or (nearest[0] if nearest else None) or f"建筑_{len(buildings) + 1}"
            height = float(_xdata_value(entity, 1040) or (nearest[1] if nearest and nearest[1] is not None else 0.0))
            buildings.append(
                Building(
                    name=str(name),
                    polygon=polygon,
                    height=height,
                    btype=_building_type(layer, str(name), height),
                    layer=layer,
                )
            )

    roads: list[Road] = []
    used_road_text_indexes: set[int] = set()
    if road_polys:
        # 闭合道路红线已是面域，按相交/相邻合并。
        merged = unary_union([p.buffer(0) for p in road_polys])
        geoms = list(merged.geoms) if hasattr(merged, "geoms") else [merged]
        for idx, geom in enumerate(geoms):
            nearest = _nearest_road_text_to_geometry(geom, road_texts, used_road_text_indexes)
            name, width = (nearest[0], nearest[1]) if nearest else (f"道路{idx + 1}", 24.0)
            centerline = centerlines[idx] if idx < len(centerlines) else None
            roads.append(Road(name=name, polygon=geom, centerline=centerline, width=width, source_layer="ROAD_REDLINE"))

    if not roads and road_lines:
        # 真实/简化图纸常把道路红线画成两条未闭合边线。此时优先用道路中心线
        # 与文字标注宽度构造道路面域；没有中心线时再用红线两两合并的兜底策略。
        if centerlines:
            for idx, centerline in enumerate(centerlines):
                nearest = _road_text_for_centerline(centerline, road_texts, used_road_text_indexes)
                name, width = (nearest[0], nearest[1]) if nearest else (f"道路{idx + 1}", 24.0)
                roads.append(
                    Road(
                        name=name,
                        polygon=centerline.buffer(width / 2.0, cap_style="square", join_style="mitre"),
                        centerline=centerline,
                        width=width,
                        source_layer="ROAD_CENTERLINE+ROAD_REDLINE",
                    )
                )
        else:
            for idx, line in enumerate(road_lines):
                nearest = _nearest_text((line.centroid.x, line.centroid.y), road_texts)
                name, width = (nearest[0], nearest[1]) if nearest else (f"道路{idx + 1}", 24.0)
                roads.append(
                    Road(
                        name=name,
                        polygon=line.buffer(width / 2.0, cap_style="square", join_style="mitre"),
                        centerline=line,
                        width=width,
                        source_layer="ROAD_REDLINE_BUFFERED",
                    )
                )

    return DrawingData(roads=roads, buildings=buildings)
