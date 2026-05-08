from __future__ import annotations

import copy
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

import warnings

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
from langgraph.graph import END, StateGraph

warnings.filterwarnings(
    "ignore",
    category=LangChainPendingDeprecationWarning,
    message=r"The default value of `allowed_objects` will change in a future version.*",
)

from app.converter import ConversionResult, prepare_cad_input
from app.dwg_parser import parse_converted_dwg_dxf
from app.dwg_profile import get_dwg_profile
from app.models import DrawingData, ReviewResult, Timing
from app.parser import parse_drawing
from app.renderer import render_report
from app.reviewer import review_drawing


@dataclass
class LLMConfig:
    """预留大模型 API 配置位置。

    当前 Demo 的几何审查算法全部在本地确定性执行，不依赖大模型。
    如果后续需要让 Agent 调用 LLM 生成解释、补全文本或解析复杂规范，
    可以在这里填入供应商、模型名和 API Key 环境变量名。
    """

    provider: str = "openai-compatible"
    model: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"

    @property
    def api_key(self) -> str | None:
        """从环境变量读取 API Key。当前 Demo 默认不会调用。"""

        return os.getenv(self.api_key_env)

    @property
    def base_url(self) -> str | None:
        """从环境变量读取 OpenAI-compatible base URL。当前 Demo 默认不会调用。"""

        return os.getenv(self.base_url_env)


@dataclass
class AgentContext:
    """一次审查任务的完整上下文，随 LangGraph 状态在各 Agent 间流转。"""

    # input_path: 用户上传或 CLI 传入的原始 CAD 路径，可以是 DXF 或 DWG。
    input_path: Path
    # output_dir: 本次任务的输出目录，报告、图片和 timing JSON 都写到这里。
    output_dir: Path
    # review_path: 实际用于审查的 DXF 路径；DWG 转换后指向转换产物，DXF 输入则指向自身。
    review_path: Path | None = None
    # conversion: ConvertAgent 的转换结果，记录是否转换、耗时和转换步骤。
    conversion: ConversionResult | None = None
    # drawing: ParseAgent 输出的结构化图纸对象。
    drawing: DrawingData | None = None
    # results: ReviewAgent 输出的逐栋审查结果。
    results: list[ReviewResult] | None = None
    # timing: 全链路耗时统计。
    timing: Timing = field(default_factory=Timing)
    # artifacts: ReportAgent 输出的文件路径字典，例如 report/image/timing。
    artifacts: dict[str, Path] | None = None
    # llm_config: 预留大模型配置，当前几何审查不依赖 LLM。
    llm_config: LLMConfig = field(default_factory=LLMConfig)
    # dwg_mode: 保留旧字段用于兼容调用方；实际 DWG 解析统一使用严格模式。
    dwg_mode: str = "strict"


class WorkflowState(TypedDict, total=False):
    """LangGraph 节点之间传递的状态。ctx 保存完整审查上下文。"""

    ctx: AgentContext


class BaseAgent:
    """所有 Agent 的公共接口，便于 LangGraph 节点复用和单独测试。"""

    name = "base"

    def run(self, _ctx: AgentContext) -> AgentContext:
        raise NotImplementedError


class ConvertAgent(BaseAgent):
    """格式转换 Agent：DWG 自动转换为 DXF，DXF 则直接透传。"""

    name = "convert_agent"

    def run(self, ctx: AgentContext) -> AgentContext:
        conversion = prepare_cad_input(ctx.input_path, ctx.output_dir)
        ctx.conversion = conversion
        ctx.review_path = conversion.review_path
        ctx.timing.t_convert = conversion.t_convert
        return ctx


class ParseAgent(BaseAgent):
    """图纸解析 Agent：读取 DXF 并抽取道路红线、道路宽度和建筑轮廓。"""

    name = "parse_agent"

    def run(self, ctx: AgentContext) -> AgentContext:
        started = time.perf_counter()
        if ctx.conversion and ctx.conversion.converted:
            profile = get_dwg_profile(ctx.dwg_mode)
            ctx.conversion.steps.append(
                f"使用 DWG 专用解析器：{profile.label}，按真实图纸图层/块参照/填充/线图元进行抽取，不影响原 DXF 解析逻辑。"
            )
            ctx.drawing = parse_converted_dwg_dxf(ctx.review_path or ctx.input_path, profile=profile)
        else:
            ctx.drawing = parse_drawing(ctx.review_path or ctx.input_path)
        ctx.timing.t_parse = time.perf_counter() - started
        return ctx


class ReviewAgent(BaseAgent):
    """规则审查 Agent：调用退让距离、Q 值查询和合规判定算法。"""

    name = "review_agent"

    def run(self, ctx: AgentContext) -> AgentContext:
        started = time.perf_counter()
        if ctx.drawing is None:
            raise RuntimeError("ParseAgent must run before ReviewAgent")
        ctx.results = review_drawing(ctx.drawing)
        ctx.timing.t_review = time.perf_counter() - started
        return ctx


class ReportAgent(BaseAgent):
    """报告 Agent：输出 HTML 报告、标注图片和单图纸 timing JSON。"""

    name = "report_agent"

    def run(self, ctx: AgentContext) -> AgentContext:
        started = time.perf_counter()
        if ctx.drawing is None or ctx.results is None:
            raise RuntimeError("ParseAgent and ReviewAgent must run before ReportAgent")
        report_input = ctx.review_path or ctx.input_path

        if not (ctx.conversion and ctx.conversion.converted):
            ctx.artifacts = render_report(
                report_input,
                ctx.output_dir,
                ctx.drawing,
                ctx.results,
                ctx.timing,
                conversion_steps=ctx.conversion.steps if ctx.conversion else [],
                original_input=ctx.input_path,
            )
            ctx.timing.t_render = time.perf_counter() - started
            self._rewrite_final_timing(ctx)
            return ctx

        from app.dwg_renderer import render_dwg_scenario_report

        ctx.artifacts = {}
        scenario_summaries: dict[str, list[ReviewResult]] = {}
        scenario_titles = {
            "site_prop_redline": "第二组：G-SITE-PROP / 总图-征地红线核心红线退避计算",
            "building_site_open_redline": "第三组：建筑高层多层/屋顶外轮廓 + 用地/征地红线 + 开放空间核心红线退避计算",
        }
        for scenario_key in ("site_prop_redline", "building_site_open_redline"):
            title = scenario_titles[scenario_key]
            scenario_roads = ctx.drawing.scenario_core_redlines.get(scenario_key, [])
            scenario_buildings = ctx.drawing.scenario_buildings.get(scenario_key, ctx.drawing.buildings)
            scenario_drawing = copy.copy(ctx.drawing)
            scenario_drawing.roads = scenario_roads
            scenario_drawing.buildings = scenario_buildings
            scenario_drawing.parse_warnings = [*ctx.drawing.parse_warnings, f"{title}：本图仅使用该场景核心红线集合参与退避计算。"]
            scenario_results = review_drawing(scenario_drawing)
            scenario_summaries[scenario_key] = scenario_results
            scenario_artifacts = render_dwg_scenario_report(
                report_input,
                ctx.output_dir,
                scenario_drawing,
                scenario_results,
                ctx.timing,
                conversion_steps=ctx.conversion.steps if ctx.conversion else [],
                original_input=ctx.input_path,
                suffix=scenario_key,
                title=title,
            )
            prefixed = {f"{scenario_key}_{key}": value for key, value in scenario_artifacts.items()}
            ctx.artifacts.update(prefixed)
        ctx.results = scenario_summaries.get("site_prop_redline", [])
        ctx.timing.t_render = time.perf_counter() - started
        self._rewrite_final_timing(ctx)
        return ctx

    @staticmethod
    def _rewrite_final_timing(ctx: AgentContext) -> None:
        """渲染结束后回写最终耗时，保证 timing JSON 与内存上下文一致。"""

        if not ctx.artifacts:
            return
        timing_paths = [path for key, path in ctx.artifacts.items() if key.endswith("timing")]
        if not timing_paths:
            return
        for timing_path in timing_paths:
            timing_path.write_text(
                json.dumps(
                    {
                        "t_convert": ctx.timing.t_convert,
                        "t_parse": ctx.timing.t_parse,
                        "t_review": ctx.timing.t_review,
                        "t_render": ctx.timing.t_render,
                        "t_total": ctx.timing.t_total,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )


class LangGraphReviewWorkflow:
    """基于 LangGraph StateGraph 的建筑退让审查 Agent 编排器。

    图结构为：parse -> review -> report -> END。
    每个节点由一个独立 Agent 执行，满足题目对 Agent 框架的要求，
    同时保留确定性算法，避免把几何计算交给大模型导致不可复现。
    """

    def __init__(self, llm_config: LLMConfig | None = None) -> None:
        self.llm_config = llm_config or LLMConfig()
        self.convert_agent = ConvertAgent()
        self.parse_agent = ParseAgent()
        self.review_agent = ReviewAgent()
        self.report_agent = ReportAgent()
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """构建 LangGraph 有向流程图。"""

        builder = StateGraph(WorkflowState)
        builder.add_node("convert", self._convert_node)
        builder.add_node("parse", self._parse_node)
        builder.add_node("review", self._review_node)
        builder.add_node("report", self._report_node)
        builder.set_entry_point("convert")
        builder.add_edge("convert", "parse")
        builder.add_edge("parse", "review")
        builder.add_edge("review", "report")
        builder.add_edge("report", END)
        return builder.compile()

    def _convert_node(self, state: WorkflowState) -> WorkflowState:
        return {"ctx": self.convert_agent.run(state["ctx"])}

    def _parse_node(self, state: WorkflowState) -> WorkflowState:
        return {"ctx": self.parse_agent.run(state["ctx"])}

    def _review_node(self, state: WorkflowState) -> WorkflowState:
        return {"ctx": self.review_agent.run(state["ctx"])}

    def _report_node(self, state: WorkflowState) -> WorkflowState:
        return {"ctx": self.report_agent.run(state["ctx"])}

    def run(self, input_path: str | Path, output_dir: str | Path, dwg_mode: str = "strict") -> AgentContext:
        """执行一次完整审查任务。

        dwg_mode 参数仅为兼容旧调用方保留，DWG 实际统一使用严格模式。
        """

        ctx = AgentContext(
            input_path=Path(input_path),
            output_dir=Path(output_dir),
            artifacts={},
            llm_config=self.llm_config,
            dwg_mode=dwg_mode,
        )
        final_state = self.graph.invoke({"ctx": ctx})
        return final_state["ctx"]


# 兼容原有 CLI 导入名；实际实现已经升级为 LangGraph。
ReviewWorkflow = LangGraphReviewWorkflow
