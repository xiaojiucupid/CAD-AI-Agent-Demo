from __future__ import annotations

import math
import re
from pathlib import Path

import ezdxf
from shapely.geometry import LineString
from shapely.ops import unary_union

from app.geometry import make_linestring, make_polygon
from app.models import Building, DrawingData, Road


# 本文件是“标准 DXF”解析器，面向 test_site_01.dxf / test_site_02.dxf 这类
# 图层约定清楚的简化测试图。DWG 转换后的真实图纸走 app/dwg_parser.py。

# WIDTH_RE: 从道路文字中提取道路宽度，例如 “道路A W=24m” 或 “红线宽度=36米”。
WIDTH_RE = re.compile(r"(?:W|宽|红线宽度)\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m|米)?", re.IGNORECASE)
# ROAD_NAME_RE: 从道路文字中提取道路名称，例如 “道路A”“文一路”“XX大道”。
ROAD_NAME_RE = re.compile(r"(道路[^:：\s]+|[^:：\s]+路|[^:：\s]+街|[^:：\s]+大道)")
# HEIGHT_RE: 从建筑文字中提取建筑高度，例如 “H=18m”“建筑高度=54米”。
HEIGHT_RE = re.compile(r"(?:H|高度|建筑高度)\s*[=:：]?\s*([0-9]+(?:\.[0-9]+)?)\s*(?:m|米)?", re.IGNORECASE)
# NAME_RE: 从建筑文字中提取建筑名称，例如 “建筑=B1”“楼号=3#”。
NAME_RE = re.compile(r"(?:建筑|楼栋|楼号)\s*[=:：]?\s*([^,，;；\s]+)")


def _polyline_points(entity) -> list[tuple[float, float]]:
    """读取 LWPOLYLINE 的二维点坐标。

    entity: ezdxf 中的 LWPOLYLINE 图元。
    返回值: [(x, y), ...]，单位沿用 CAD 图纸单位。
    """

    return [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]


def _xdata_value(entity, code: int):
    """读取 HZPLAN 扩展数据中的指定 code 值。

    entity: CAD 图元。
    code: XDATA 组码。当前约定 1000=建筑名称，1040=建筑高度。
    返回值: 找到则返回原值，找不到或图元没有 XDATA 时返回 None。
    """

    try:
        for item in entity.get_xdata("HZPLAN"):
            if item.code == code:
                return item.value
    except Exception:
        # 很多图元没有 HZPLAN XDATA，属于正常情况，直接回退到文字识别。
        return None
    return None


def _text_content(entity) -> str:
    """兼容读取 TEXT 与 MTEXT 内容，用于提取道路名称、宽度、建筑名称和高度。"""

    if entity.dxftype() == "MTEXT":
        try:
            # MTEXT 可能包含控制符，plain_text() 会尽量返回纯文本。
            return entity.plain_text()
        except Exception:
            return getattr(entity, "text", "") or getattr(entity.dxf, "text", "")
    return getattr(entity.dxf, "text", "") or getattr(entity, "text", "")


def _text_insert_point(entity) -> tuple[float, float]:
    """读取文字插入点。

    文字位置用于把道路宽度文字匹配到最近道路、把建筑高度文字匹配到最近建筑。
    """

    point = getattr(entity.dxf, "insert", None)
    if point is None:
        return (0.0, 0.0)
    return (float(point.x), float(point.y))


def _collect_road_text(modelspace) -> list[tuple[str, float, tuple[float, float], str | None]]:
    """收集道路文字标注。

    modelspace: DXF 模型空间。
    返回值元素为 (道路名称, 道路宽度, 文字坐标, 方向提示)。
    方向提示用于多条道路都很近时，优先把横向文字匹配给横向道路。
    """

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
    """收集建筑名称和高度文字。

    返回值元素为 (建筑名称或 None, 建筑高度或 None, 文字坐标)。
    后续会用最近邻把文字匹配给建筑轮廓。
    """

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
    """从文字列表中找离指定点最近的一条。

    point: 通常是道路或建筑的 centroid。
    texts: `_collect_road_text` 或 `_collect_building_text` 的结果。
    """

    if not texts:
        return None
    px, py = point
    return min(texts, key=lambda item: math.hypot(px - item[2][0], py - item[2][1]))


def _nearest_road_text_to_geometry(geometry, texts, used_indexes: set[int]):
    """给道路面域匹配最近且未使用的道路文字。"""

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
    """从文字内容中识别道路方向提示。"""

    if "南北" in raw or "纵" in raw or "竖" in raw:
        return "vertical"
    if "东西" in raw or "横" in raw:
        return "horizontal"
    return None


def _road_text_for_centerline(centerline: LineString, texts, used_indexes: set[int]):
    """给道路中心线匹配道路名称和宽度文字。

    优先使用方向一致的文字；如果没有方向提示，再使用最近文字。
    """

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
    """根据图层、名称和高度粗略推断建筑类型。"""

    text = f"{layer}_{name}".upper()
    if "HIGH" in text or height >= 50:
        return "高层"
    if "MULTI" in text or height >= 10:
        return "多层"
    return "低层"


def parse_drawing(path: str | Path) -> DrawingData:
    """解析标准 DXF 中的道路红线与建筑轮廓。

    输入要求：
    - 道路红线图层：ROAD_REDLINE；
    - 道路中心线图层：ROAD_CENTERLINE；
    - 建筑图层：BUILDING_LOW / BUILDING_MULTI / BUILDING_HIGH；
    - 道路宽度文字：例如 W=24m；
    - 建筑高度文字或 XDATA：例如 H=18m 或 HZPLAN/1040。
    """

    path = Path(path)
    if path.suffix.lower() == ".dwg":
        raise ValueError(
            "检测到 DWG 输入。当前 Demo 仅直接解析 DXF，请先使用 ODA File Converter、AutoCAD 或 Teigha 将 DWG 转为 DXF 后再审查。"
        )

    # doc: ezdxf 读取后的文档对象。
    doc = ezdxf.readfile(path)
    # msp: 模型空间，包含总平面图中的几何图元和文字图元。
    msp = doc.modelspace()
    # road_texts: 道路名称和道路宽度标注。
    road_texts = _collect_road_text(msp)
    # building_texts: 建筑名称和建筑高度标注。
    building_texts = _collect_building_text(msp)
    # road_polys: 已闭合的道路红线面域。
    road_polys = []
    # road_lines: 未闭合的道路红线边线。
    road_lines: list[LineString] = []
    # buildings: 解析出的建筑对象。
    buildings: list[Building] = []
    # centerlines: 道路中心线。
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

    # roads: 最终道路对象。优先用道路面域，其次中心线+宽度，最后边线+宽度。
    roads: list[Road] = []
    # used_road_text_indexes: 防止多条道路重复使用同一个宽度文字。
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
        # 与文字标注宽度构造道路面域；没有中心线时再用红线边线 buffer 兜底。
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
