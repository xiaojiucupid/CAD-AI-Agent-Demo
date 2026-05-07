from __future__ import annotations

import html
import json
from pathlib import Path
from textwrap import wrap

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon as MplPolygon

from app.models import DrawingData, ReviewResult, Timing


# 本文件负责报告输出：一张 PNG 标注图、一份 HTML 审查报告、一份 timing JSON。
# 规则审查已经在 reviewer.py 完成，这里只做结果可视化和文本组织。


def _configure_chinese_font() -> None:
    """尽量选择 Windows 常见中文字体，避免标注图乱码。"""

    candidates = ["Microsoft YaHei", "SimHei", "SimSun", "Noto Sans CJK SC"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return


def _plot_polygon(ax, polygon, **kwargs) -> None:
    """把 Shapely Polygon/MultiPolygon 绘制到 Matplotlib 坐标轴。"""

    if polygon.is_empty:
        return
    geoms = list(polygon.geoms) if hasattr(polygon, "geoms") else [polygon]
    for geom in geoms:
        if geom.is_empty or not hasattr(geom, "exterior"):
            continue
        x, y = geom.exterior.xy
        ax.add_patch(MplPolygon(list(zip(x, y)), closed=True, **kwargs))


def _short_name(name: str) -> str:
    """缩短建筑名，避免标注图中标签过长。"""

    return name.split("_", 1)[0] if "_" in name else name


def _worst_result(results: list[ReviewResult], building_name: str) -> ReviewResult | None:
    """返回某栋建筑最严重的一条审查结果。"""

    related = [r for r in results if r.building_name == building_name]
    if not related:
        return None
    return min(related, key=lambda r: r.actual_setback - r.required_setback)


def _plot_linestring(ax, line, **kwargs) -> None:
    """把 Shapely LineString/MultiLineString 绘制到 Matplotlib 坐标轴。"""

    if line is None or line.is_empty:
        return
    geoms = list(line.geoms) if hasattr(line, "geoms") else [line]
    for geom in geoms:
        if geom.is_empty or not hasattr(geom, "xy"):
            continue
        x, y = geom.xy
        ax.plot(x, y, **kwargs)


def _problem_legend_items(results: list[ReviewResult]) -> list[ReviewResult]:
    """每栋不合规建筑只保留最严重问题，用于右侧问题清单。"""

    failed_by_building: dict[str, ReviewResult] = {}
    for result in results:
        if result.passed:
            continue
        current = failed_by_building.get(result.building_name)
        if current is None or (result.actual_setback - result.required_setback) < (current.actual_setback - current.required_setback):
            failed_by_building[result.building_name] = result
    return sorted(failed_by_building.values(), key=lambda item: _short_name(item.building_name))


def _draw_problem_panel(fig, problems: list[ReviewResult]) -> None:
    """在标注图右侧绘制问题清单面板。"""

    panel = fig.add_axes([0.78, 0.14, 0.2, 0.72])
    panel.axis("off")
    panel.text(0, 1, "问题清单", fontsize=13, fontweight="bold", color="#7f1d1d", va="top")
    if not problems:
        panel.text(0, 0.92, "未发现不合规问题", fontsize=9, color="#166534", va="top")
        return
    y = 0.92
    for idx, problem in enumerate(problems, start=1):
        short_name = _short_name(problem.building_name)
        text = f"{idx}. {short_name}  临 {problem.road_name}\n实际 {problem.actual_setback:g}m < 理论 {problem.required_setback:g}m"
        wrapped = []
        for line in text.split("\n"):
            wrapped.extend(wrap(line, width=18) or [line])
        panel.text(
            0,
            y,
            "\n".join(wrapped),
            fontsize=8.5,
            color="#7f1d1d",
            va="top",
            bbox={"boxstyle": "round,pad=0.3", "facecolor": "#fff1f2", "edgecolor": "#fecdd3", "alpha": 0.95},
        )
        y -= 0.11 + 0.035 * max(0, len(wrapped) - 2)
        if y < 0.04 and idx < len(problems):
            panel.text(0, y, f"……另 {len(problems) - idx} 项见报告", fontsize=8.5, color="#7f1d1d", va="top")
            break


def render_annotation_image(output_png: Path, data: DrawingData, results: list[ReviewResult]) -> None:
    """生成总平面审查标注图。"""

    _configure_chinese_font()
    # failed: 不合规建筑名称集合，用于决定建筑轮廓颜色。
    failed = {r.building_name for r in results if not r.passed}
    # problems: 每栋不合规建筑最严重的问题，用于右侧问题清单。
    problems = _problem_legend_items(results)
    fig, ax = plt.subplots(figsize=(16, 10))
    fig.subplots_adjust(left=0.06, right=0.75, top=0.92, bottom=0.08)

    # 先绘制道路底图：浅蓝面域、红色道路红线边界、绿色中心线。
    for road in data.roads:
        _plot_polygon(ax, road.polygon, facecolor="#dbeafe", edgecolor="#dc2626", alpha=0.38, linewidth=2.0, zorder=1)
        if road.centerline is not None:
            _plot_linestring(ax, road.centerline, color="#16a34a", linewidth=2.2, linestyle="--", zorder=2)
        c = road.polygon.representative_point()
        ax.text(
            c.x,
            c.y,
            f"{road.name}\nW={road.width:g}m",
            fontsize=9,
            color="#1e3a8a",
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.24", "facecolor": "#eff6ff", "edgecolor": "#93c5fd", "alpha": 0.9},
            zorder=4,
        )

    # 再绘制建筑轮廓；建筑内部只保留短标签 B1、B2 等，避免图面拥挤。
    for idx, building in enumerate(data.buildings, start=1):
        is_failed = building.name in failed
        fill = "#fecaca" if is_failed else "#bbf7d0"
        edge = "#dc2626" if is_failed else "#16a34a"
        _plot_polygon(ax, building.polygon, facecolor=fill, edgecolor=edge, alpha=0.62, linewidth=2.4, zorder=3)
        c = building.polygon.representative_point()
        label = _short_name(building.name)
        ax.text(
            c.x,
            c.y,
            label,
            ha="center",
            va="center",
            fontsize=8,
            color="#111827",
            bbox={"boxstyle": "round,pad=0.22", "facecolor": "white", "edgecolor": edge, "alpha": 0.88},
            zorder=5,
        )


    _draw_problem_panel(fig, problems)

    ax.legend(
        handles=[
            Patch(facecolor="#bbf7d0", edgecolor="#16a34a", label="合规建筑"),
            Patch(facecolor="#fecaca", edgecolor="#dc2626", label="不合规建筑"),
            Patch(facecolor="#dbeafe", edgecolor="#dc2626", label="道路红线边界"),
            Line2D([0], [0], color="#16a34a", lw=2.2, linestyle="--", label="道路中心线"),
        ],
        loc="upper right",
        framealpha=0.94,
    )
    ax.set_aspect("equal", adjustable="box")
    ax.autoscale_view()
    ax.margins(0.08)
    ax.grid(True, linestyle="--", alpha=0.18)
    ax.set_xlabel("X / m")
    ax.set_ylabel("Y / m")
    ax.set_title("建筑退让道路红线审查标注图", fontsize=15, fontweight="bold")
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=180, bbox_inches="tight")
    plt.close(fig)


def render_report(
    input_path: Path,
    output_dir: Path,
    data: DrawingData,
    results: list[ReviewResult],
    timing: Timing,
    conversion_steps: list[str] | None = None,
    original_input: Path | None = None,
) -> dict[str, Path]:
    """生成 HTML 报告、PNG 标注图和 timing JSON。"""

    stem = input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / f"{stem}_annotation.png"
    html_path = output_dir / f"{stem}_report.html"
    log_path = output_dir / f"{stem}_timing.json"
    render_annotation_image(image_path, data, results)

    # building_names: 所有建筑名称集合，用于统计合规/不合规建筑数量。
    building_names = {b.name for b in data.buildings}
    # failed_buildings: 至少有一条审查不合规的建筑集合。
    failed_buildings = {r.building_name for r in results if not r.passed}
    passed_count = len(building_names - failed_buildings)
    failed_count = len(failed_buildings)

    rows = "\n".join(
        f"<tr class='{'' if r.passed else 'fail'}'><td>{html.escape(r.building_name)}</td><td>{r.building_type}</td>"
        f"<td>{r.height:.2f}</td><td>{html.escape(r.road_name)}</td><td>{r.actual_setback:.2f}</td>"
        f"<td>{r.required_setback:.2f}</td><td>{'合规' if r.passed else '不合规'}</td><td>{html.escape(r.reason)}</td></tr>"
        for r in results
    )
    problems = "".join(f"<li>{html.escape(r.building_name)} 临 {html.escape(r.road_name)}：实际 {r.actual_setback:.2f}m，小于理论 {r.required_setback:.2f}m</li>" for r in results if not r.passed) or "<li>未发现不合规问题</li>"
    conversion_items = "".join(f"<li>{html.escape(step)}</li>" for step in (conversion_steps or [])) or "<li>DXF 直接解析，无格式转换。</li>"
    source_name = original_input.name if original_input else input_path.name
    warning_items = "".join(f"<li>{html.escape(item)}</li>" for item in data.parse_warnings)
    warning_block = f"<h2>解析置信度与复核提示</h2><div class='warn'><b>解析模式：</b>{html.escape(data.parse_mode)}；<b>置信度：</b>{html.escape(data.confidence)}</div><ul>{warning_items}</ul>" if data.parse_warnings else ""

    html_text = f"""<!doctype html>
<html lang='zh-CN'>
<head><meta charset='utf-8'><title>{stem} 建筑退让审查报告</title>
<style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;margin:32px;color:#1a202c;line-height:1.6}}h1{{color:#1a365d}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #cbd5e0;padding:8px}}th{{background:#edf2f7}}.fail{{background:#fff5f5;color:#9b2c2c}}.card{{background:#f7fafc;border-left:4px solid #3182ce;padding:12px 16px;margin:16px 0}}.warn{{background:#fffbeb;border-left:4px solid #f59e0b;padding:12px 16px;margin:16px 0;color:#92400e}}img{{max-width:100%;border:1px solid #e2e8f0}}</style></head>
<body>
<h1>建筑退让道路红线自动审查报告</h1>
<div class='card'><b>项目概览</b><br>原始图纸：{html.escape(source_name)}<br>审查图纸：{html.escape(input_path.name)}<br>道路数量：{len(data.roads)}；建筑数量：{len(data.buildings)}<br>审查依据：《杭州市城市规划管理技术规定（2026）》第三部分（四）第2款表3-2、第3款道路交叉口退让要求（Demo结构化实现）</div>
<h2>CAD 输入与转换过程</h2><ol>{conversion_items}</ol>
{warning_block}
<h2>逐栋审查明细表</h2><table><thead><tr><th>建筑名称</th><th>类型</th><th>高度(m)</th><th>临接道路</th><th>实际让距(m)</th><th>理论让距(m)</th><th>判定</th><th>依据链</th></tr></thead><tbody>{rows}</tbody></table>
<h2>总平面标注图</h2><p>建筑内部仅保留短标签；绿色为合规建筑，红色为不合规建筑；道路红线为红色边界，中心线为绿色虚线，右侧为问题清单图例。</p><img src='{image_path.name}' alt='annotation'>
<h2>审查结论摘要</h2><p>合规建筑：{passed_count} 栋；不合规建筑：{failed_count} 栋。</p><ul>{problems}</ul>
<h2>速度测试</h2><pre>t_convert={timing.t_convert:.4f}s\nt_parse={timing.t_parse:.4f}s\nt_review={timing.t_review:.4f}s\nt_render={timing.t_render:.4f}s\nt_total={timing.t_total:.4f}s</pre>
</body></html>"""
    html_path.write_text(html_text, encoding="utf-8")
    log_path.write_text(
        json.dumps(
            {
                "t_convert": timing.t_convert,
                "t_parse": timing.t_parse,
                "t_review": timing.t_review,
                "t_render": timing.t_render,
                "t_total": timing.t_total,
                "conversion_steps": conversion_steps or [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"html": html_path, "image": image_path, "timing": log_path}
