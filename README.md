# 建筑退让道路红线自动审查 Demo

本项目用于完成“二轮测试题目”中的 `建筑退让道路红线审查` 模块 Demo。
输入为 CAD 总平面图（当前直接支持 `DXF`），输出为 `HTML 审查报告 + 标注图片 + 速度日志`。

## 1. 功能范围

当前 Demo 已实现以下两类规则：

- 《杭州市城市规划管理技术规定（2026）》第三部分 建筑管理 /（四）建筑退让 / 第 2 款：沿城市道路两侧新建建筑后退道路规划红线最小距离（表 3-2 的 Demo 化结构实现）
- 第 3 款：道路交叉口四周建筑后退道路红线要求（Demo 中实现为交叉口附加退让）

说明：

- 当前仓库中的规范逻辑采用“可运行 Demo 的结构化规则链”实现，便于在面试中演示 Agent 化拆解、几何计算和报告生成全流程。
- 由于题目说明中未直接给出完整表 3-2 数值矩阵，本项目将 `Q 值` 和 `最小退让` 设计为可替换函数，后续只需替换 `app/rules.py` 即可接入正式条文数值。

## 2. Agent 架构设计

项目没有把流程写成单一脚本，而是采用 `LangGraph StateGraph` 实现 Agent 编排，入口位于 `app/agent.py`。

当前图工作流为：

```text
parse_agent -> review_agent -> report_agent -> END
```

1. `parse_agent`
   - 负责解析 DXF 图纸
   - 提取道路红线、道路名称/宽度、建筑轮廓、建筑高度
   - 记录 `t_parse`

2. `review_agent`
   - 负责逐栋建筑与道路建立邻接关系
   - 调用规则引擎进行 `Q 值查询`、`最小让距查表`、`交叉口附加判定`
   - 输出逐栋审查明细
   - 记录 `t_review`

3. `report_agent`
   - 负责绘制总平面标注图
   - 负责渲染 HTML 报告和 timing JSON
   - 记录 `t_render`

这种拆分方式的优点：

- 明确满足题目中的 Agent 框架要求，且可在代码中直接看到 LangGraph 节点与边
- 职责边界清晰，便于解释
- 规则层与图形解析层解耦，方便后续扩展表 3-3 / 表 3-4
- 每个阶段都有独立耗时统计，便于速度优化
- 后续可以继续加入 `llm_explain_agent`、`human_review_agent` 等节点

### 2.1 API 与密钥预留

当前几何审查、规则判定和报告生成均可离线运行，不强制依赖大模型 API。为了后续扩展 Agent 的文本解释、规则问答或报告润色，`app/agent.py` 已预留 `LLMConfig`：

```bash
$env:OPENAI_BASE_URL="https://your-api-base/v1"
$env:OPENAI_API_KEY="your-api-key"
```

可在 `LLMConfig` 中配置：

- `provider`
- `model`
- `api_key_env`
- `base_url_env`

后续如果接入 OpenAI 兼容 API、LangChain ChatModel 或自定义推理服务，可以直接在新增 LangGraph Agent 节点中读取这些配置。

## 3. 目录结构

```text
二轮题测/
├─ app/
│  ├─ agent.py       # Agent 编排与上下文
│  ├─ cli.py         # 命令行入口
│  ├─ geometry.py    # 几何计算
│  ├─ models.py      # 数据模型
│  ├─ parser.py      # DXF 解析
│  ├─ renderer.py    # HTML 报告与标注图渲染
│  ├─ reviewer.py    # 审查流程
│  └─ rules.py       # 规则引擎（Q 值、查表、交叉口）
├─ tests/
│  └─ test_rules.py  # 核心规则断言
├─ outputs/          # 生成的报告与速度日志
├─ main.py           # 启动入口
└─ requirements.txt
```

## 4. 环境安装

建议 Python 版本：`3.11+`

### Windows PowerShell

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 5. 运行方式

### 方式一：自动扫描当前目录全部 DXF

```bash
python main.py
```

### 方式二：指定一个或多个图纸

```bash
python main.py test_site_01.dxf test_site_02.dxf --output outputs
```

### 方式三：启动 Web 上传界面

```bash
python -m app.web
```

然后在浏览器打开：

```text
http://127.0.0.1:5000
```

界面支持上传 `DXF/DWG` 文件，点击“开始解析并生成报告”后，会自动执行 `ConvertAgent -> ParseAgent -> ReviewAgent -> ReportAgent`，并在页面中返回转换过程、项目概览、耗时统计、HTML 报告预览、标注图和 timing JSON 链接。`DWG` 自动转换依赖 ODA File Converter，可设置环境变量：

```powershell
$env:ODA_FILE_CONVERTER="C:\\Program Files\\ODA\\ODAFileConverter\\ODAFileConverter.exe"
```

如果未安装转换工具，系统会在页面和报告中给出文字提示。

运行完成后会在 `outputs/` 下生成：

- `*_report.html`：图文审查报告
- `*_annotation.png`：总平面标注图
- `*_timing.json`：单图纸耗时日志
- `speed_summary.json`：多图纸汇总耗时日志

## 6. 当前图纸约定

为了让 Demo 在 2 天内可稳定运行，当前解析器对图层和标注有如下约定：

### 道路

- 道路红线图层：`ROAD_REDLINE`
- 道路中心线图层：`ROAD_CENTERLINE`（可选）
- 道路宽度从图中文字提取，例如：`道路A W=24m`

### 建筑

- 建筑图层：`BUILDING_LOW` / `BUILDING_MULTI` / `BUILDING_HIGH`
- 建筑名称读取 `HZPLAN` 扩展数据中 `1000` 字段
- 建筑高度读取 `HZPLAN` 扩展数据中 `1040` 字段

如果没有读到名称或高度，会自动回退为默认值。

## 7. 规则实现说明

### 7.1 表 3-2（Demo 结构化实现）

当前逻辑位于 `app/rules.py`：

1. 按道路宽度分档
   - `<20m`
   - `20m~40m`
   - `>40m`

2. 计算 `Q 值`
   - 当前 Demo 用 `Q = 建筑高度 / 2`
   - 该逻辑是为了演示“规范参数查询函数”可插拔

3. 查最小退让
   - `minimum_setback = max(道路分档基线, Q)`

### 7.2 道路交叉口规则（第 3 款 Demo 化）

- 若同一建筑同时邻接两条及以上道路，则视为触发交叉口附加约束
- 当前 Demo 实现为：`required_setback += 2.0m`

### 7.3 实际让距计算

- 使用 `shapely` 计算建筑轮廓边界到道路红线面域边界的最短欧氏距离
- 判定允许 `±0.1m` 容差

## 8. 报告内容

HTML 报告包含：

1. 项目概览
   - 道路数量
   - 建筑数量
   - 审查依据

2. 逐栋审查明细表
   - 建筑名称
   - 建筑类型
   - 高度
   - 临接道路
   - 实际让距
   - 理论让距
   - 判定结果
   - 依据链

3. 总平面标注图
   - 合规建筑绿色显示
   - 不合规建筑红色高亮
   - 建筑标签中显示 `实际/理论让距`

4. 审查结论摘要
   - 合规/不合规建筑数量
   - 问题清单

5. 速度测试
   - `t_parse`
   - `t_review`
   - `t_render`
   - `t_total`

## 9. 核心代码可解释性

为了满足题测中“候选人必须能够完整解释核心代码”的要求，项目在以下位置保留了关键注释：

- `app/agent.py`：说明 Agent 的职责边界和编排方式
- `app/parser.py`：说明 DXF 图层约定与字段提取方式
- `app/reviewer.py`：说明建筑-道路邻接策略与让距判定逻辑
- `app/rules.py`：说明 Q 值、查表逻辑与交叉口加严逻辑

## 10. 单元测试

已提供核心规则断言：

```bash
pytest -q
```

测试覆盖：

- 道路宽度分档
- `Q 值` 计算
- 表 3-2 Demo 查表
- 交叉口附加退让
- 建筑边界到道路红线边界的退让距离计算
- 完整合规判定链路：同一道路下验证合规建筑与不合规建筑

## 11. 已知限制

1. 当前仓库直接支持 `DXF`，不直接解析 `DWG`
   - 如需处理 `test_site_03.dwg`，请先转换为 `DXF`

2. 当前规则值为 Demo 版结构化实现
   - 若拿到正式《杭州市城市规划管理技术规定（2026）》表格原文，可直接替换 `app/rules.py` 中的参数与函数

3. 复杂真实图纸可能存在图层不统一、块参照、文字旋转、外部参照等问题
   - 可在 `ParseAgent` 中继续增强图元清洗与属性识别能力

## 12. 后续可加分扩展

- 扩展表 3-3：高架 / 轨道退让
- 扩展表 3-4：高压线退让
- 自动输出 PDF
- 为真实图纸补充块参照（BLOCK/INSERT）解析
- 引入正式规范条文知识库与可追溯推理链

## 13. 交付建议

若用于提交题测，建议最终打包内容包括：

- 源代码目录
- `README.md`
- `outputs/` 中各测试图纸报告
- `outputs/speed_summary.json`
- 如有时间，可录制一个从命令执行到报告打开的演示视频
