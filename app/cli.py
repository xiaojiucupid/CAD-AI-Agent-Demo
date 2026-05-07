from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent import ReviewWorkflow


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""

    parser = argparse.ArgumentParser(description="建筑退让道路红线自动审查 Demo")
    parser.add_argument("inputs", nargs="*", help="待审查 CAD 文件路径；为空时自动扫描当前目录下的 *.dxf/*.dwg")
    parser.add_argument("--output", default="outputs", help="报告输出目录")
    parser.add_argument(
        "--dwg-mode",
        choices=["strict", "balanced", "raw"],
        default="balanced",
        help="DWG 专用解析模式：strict=严格审查，balanced=平衡识别，raw=完整解析",
    )
    return parser


def main() -> None:
    """CLI 入口：批量审查输入 CAD 并汇总速度日志。"""

    parser = build_parser()
    args = parser.parse_args()

    # inputs: 用户显式传入文件时使用传入列表；否则自动扫描当前目录下的 DXF/DWG。
    inputs = [Path(item) for item in args.inputs] if args.inputs else sorted(
        [*Path.cwd().glob("*.dxf"), *Path.cwd().glob("*.dwg")]
    )
    if not inputs:
        raise SystemExit("未找到可审查的 CAD 文件。请放入 DXF，或将 DWG 转换为 DXF 后运行。")

    workflow = ReviewWorkflow()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    # summary: 所有图纸的速度统计，最后写入 speed_summary.json。
    summary: list[dict[str, float | str]] = []
    for drawing in inputs:
        try:
            ctx = workflow.run(drawing, output_dir, dwg_mode=args.dwg_mode)
        except ValueError as exc:
            print(f"[SKIP] {drawing.name}: {exc}")
            continue
        if ctx.artifacts is None:
            raise RuntimeError("报告 Agent 未返回产物路径。")
        summary.append(
            {
                "drawing": drawing.name,
                "t_convert": ctx.timing.t_convert,
                "t_parse": ctx.timing.t_parse,
                "t_review": ctx.timing.t_review,
                "t_render": ctx.timing.t_render,
                "t_total": ctx.timing.t_total,
            }
        )
        print(f"[DONE] {drawing.name} -> {ctx.artifacts['html']}")

    if summary:
        (output_dir / "speed_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[DONE] speed log -> {output_dir / 'speed_summary.json'}")
