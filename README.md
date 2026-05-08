# 建筑退让道路红线自动审查 Agent Demo

本项目对应二轮测试题目中的 **“建筑退让道路红线审查”模块**。输入为 CAD 总平面图（`DXF/DWG`），输出为图文结合的自动审查报告，并记录全链路速度日志。

项目采用 `LangGraph` 构建多 Agent 工作流，不是单一脚本顺序执行。核心流程可离线运行，不依赖大模型 API；后续如需接入 LLM 做规范问答、报告润色或人工复核，`app/agent.py` 中已预留 `LLMConfig`。

---

## 1. 题目要求实现情况对照

| 题目要求 | 当前实现情况 | 对应代码/输出 |
|---|---|---|
| 输入 CAD 总平面图，支持 `DXF/DWG` | 已实现。DXF 直接解析；DWG 自动调用 ODA File Converter 转 DXF 后解析 | `app/parser.py`、`app/converter.py`、`app/dwg_parser.py` |
| 实现表 3-2：沿城市道路两侧建筑后退道路红线最小距离 | 已实现结构化规则表 | `app/rules.py` |
| 实现第 3 款：道路交叉口四周建筑退让要求 | 已实现交叉口上下文判断，并与表 3-2 控制值取严 | `app/reviewer.py`、`app/rules.py` |
| 实现表 3-3：建筑物离高架和匝道的距离 | 已实现。标准 DXF 可识别 `VIADUCT/ELEVATED/高架/轨道`、`RAMP/匝道` 图层；真实 DWG 通过 `DWGProfile` 配置图层关键词 | `app/parser.py`、`app/dwg_profile.py`、`app/dwg_parser.py`、`app/rules.py` |
| 使用 Agent 框架 | 已实现，使用 `LangGraph StateGraph` | `app/agent.py` |
| 不可写成单一脚本 | 已拆分为 `ConvertAgent`、`ParseAgent`、`ReviewAgent`、`ReportAgent` | `app/agent.py` |
| 输出图文结合报告 | 已实现 HTML 报告 + 总平面标注图 | `app/renderer.py`、`outputs/*_report.html` |
| 报告包含项目概览 | 已实现，道路数量、建筑数量、审查依据 | HTML 报告 |
| 报告包含逐栋审查明细表 | 已实现，包含建筑名称、类型、高度、临接道路、实际让距、理论让距、判定结果、依据链 | HTML 报告 |
| 报告包含总平面标注图 | 已实现，合规绿色，不合规红色，右侧问题清单 | `*_annotation.png` |
| 报告包含审查结论摘要 | 已实现，合规/不合规建筑数量、问题清单 | HTML 报告 |
| 记录速度日志 | 已实现 `t_parse`、`t_review`、`t_render`、`t_total`；同时额外记录 `t_convert` | `*_timing.json`、`speed_summary.json` |
| 核心算法有测试 | 已实现单元测试 | `tests/test_rules.py`、`tests/test_geometry_and_reviewer.py` |
| README 包含环境安装与启动命令 | 已实现 | 本文件第 7 节、第 17 节 |
| 关键函数有注释 | 已实现，核心 Agent、解析器、规则、审查、渲染函数均有注释 | `app/*.py` |
| 针对三份图纸输出报告 | 支持。`test_site_01.dxf`、`test_site_02.dxf` 直接审查；`test_site_03.dwg` 自动转换后审查 | `python main.py` 或 Web 上传 |

说明：题目要求速度字段为 `t_parse / t_review / t_render / t_total`。本项目在此基础上额外增加 `t_convert`，用于记录 DWG 自动转换耗时；`t_total = t_convert + t_parse + t_review + t_render`。

---

## 2. 运行结论与注意事项

### 2.1 简化 DXF 图纸

`test_site_01.dxf` 与 `test_site_02.dxf` 为简化测试图纸，图层和标注较规范，当前系统可稳定解析并生成审查报告。

### 2.2 真实 DWG 图纸

`test_site_03.dwg` 为真实图纸，图层、块参照、填充、文字、道路线和红线较复杂。系统支持：

- 自动 DWG 转 DXF。
- DWG 专用解析器。
- 单一 DWG 严格审查模式，避免多模式造成报告口径不一致。
- 解析置信度提示。
- 低置信度人工复核提示。

真实 DWG 的道路红线识别难度明显高于简化 DXF。如果报告中出现 `confidence=low` 或“道路红线识别置信度低”，应将结果作为自动初审结果，需要人工复核道路红线图层或进入后续图层配置流程。

---

## 3. 技术选型理由

| 技术 | 用途 | 选择理由 |
|---|---|---|
| `LangGraph` | Agent 编排 | 明确满足题目“必须使用 Agent 框架”的要求；节点和边清晰，便于解释和扩展 |
| `ezdxf` | DXF 解析 | 开源、稳定、适合读取 DXF 图层、文字、多段线、块参照等 |
| `shapely` | 几何计算 | 适合计算建筑轮廓、道路面域、边界距离、相交关系 |
| `matplotlib` | 标注图渲染 | 可在服务端无界面生成 PNG；已使用 `Agg` 后端避免 Web 线程 GUI 问题 |
| `Flask` | Web 上传界面 | 轻量、易演示，适合 2 天 Demo 快速交付 |
| `pytest` | 单元测试 | 覆盖核心规则和几何审查链路 |
| ODA File Converter | DWG 转 DXF | DWG 为专有二进制格式，先转 DXF 是更稳定的工程方案 |

---

## 4. Agent 架构设计

项目入口：

```text
app/agent.py
```

当前工作流：

```text
convert -> parse -> review -> report -> END
```

### 4.1 `ConvertAgent`

职责：

- 接收输入 CAD 文件。
- 判断文件类型。
- `DXF`：直接进入解析。
- `DWG`：调用 ODA File Converter 自动转换为 `DXF`。
- 记录转换过程文字。
- 记录 `t_convert`。

对应代码：

```text
app/converter.py
app/agent.py
```

### 4.2 `ParseAgent`

职责：

- 解析道路红线、道路中心线、道路宽度。
- 解析建筑轮廓、建筑高度、建筑类型。
- 标准 DXF 走 `app/parser.py`。
- DWG 转换后的 DXF 走 `app/dwg_parser.py`。
- 输出 `DrawingData`。
- 记录 `t_parse`。

### 4.3 `ReviewAgent`

职责：

- 建立建筑与临接道路关系。
- 计算实际退让距离。
- 查询表 3-2 理论退让距离。
- 判断交叉口上下文。
- 输出逐栋审查结果。
- 记录 `t_review`。

### 4.4 `ReportAgent`

职责：

- 生成 HTML 审查报告。
- 生成总平面标注图。
- 输出 timing JSON。
- 记录 `t_render`。

---

## 5. 规范依据与规则实现

### 5.1 实现条款

根据题目要求，本项目实现：

1. 《杭州市城市规划管理技术规定（2026）》第三部分 建筑管理 /（四）建筑退让 / 第 2 款：沿城市道路两侧新建建筑后退道路规划红线的最小距离（表 3-2）。
2. 第 3 款：道路交叉口四周建筑物后退道路红线距离要求。
3. 表 3-3：建筑物离高架和匝道的距离。系统把高架/轨道、匝道作为特殊线性控制对象进入同一审查链路。

说明：表 3-4（高压线退让）也已作为扩展规则保留；若图层命中高压/电力关键词，会按电压等级进行扩展审查。

### 5.2 表 3-2 结构化实现

规则代码：

```text
app/rules.py
```

当前表 3-2 结构化为：

| 道路红线宽度 | 低层骑楼 | 低层建筑 | 多层建筑 | 高层建筑 |
|---|---:|---:|---:|---:|
| 14m≤W≤20m | 2m | 3m | 5m | 5Q |
| 20m<W≤40m | 3m | 5m | 8m | 8Q |
| W>40m | 5m | 8m | 10m | 10Q |

建筑类别识别：

- 名称或类型包含“骑楼”：低层骑楼。
- 高度 ≤ 10m：低层建筑。
- 10m < 高度 ≤ 24m：多层建筑。
- 高度 > 24m：高层建筑。

说明：规范附件 2 中住宅高层阈值为 `>27m`，非单层公共建筑高层阈值为 `>24m`。当前 CAD 输入未稳定提供住宅/公共建筑功能字段，因此审查时采用更严格的 `24m` 作为高层判定阈值。

### 5.3 Q 值查询

Q 值逻辑位于：

```text
app/rules.py
```

当前代码已按规范附件 2 实现 Q 值分段：

| 建筑高度 H | Q |
|---|---:|
| 24m < H ≤ 50m | 1.0 |
| 50m < H ≤ 75m | 1.2 |
| 75m < H ≤ 100m | 1.4 |
| 100m < H ≤ 200m | 1.6 |
| H > 200m | 1.8 |

高层建筑理论退让按表 3-2 中的 `5Q / 8Q / 10Q` 计算。

### 5.4 交叉口退让

交叉口逻辑位于：

```text
app/reviewer.py
```

处理策略：

- 先筛选建筑临接道路。
- 再判断临接道路之间是否几何相交或近接。
- 确认为交叉口上下文后，按第 3 款取控制值：低、多层建筑不小于 `5m`，高层建筑不小于 `8m`。
- 最终理论让距取 `max(表3-2结果, 交叉口控制值)`。
- 避免仅因建筑离两条平行道路都较近而误触发交叉口规则。

### 5.5 表 3-3 高架/匝道退让

规则代码：

```text
app/rules.py
```

表 3-3 已结构化为以下控制值：

| 道路类型 | 居住、学校和医院类低/多层 | 居住、学校和医院类高层 | 其他建筑低/多层 | 其他建筑高层 |
|---|---:|---:|---:|---:|
| 高架 | 30m | 40m | 15m | 20m |
| 匝道 | 30m | 30m | 10m | 15m |

识别与审查方式：

- 标准 DXF：图层名包含 `VIADUCT`、`ELEVATED`、`高架`、`轨道` 时按高架/轨道控制对象处理；包含 `RAMP`、`匝道` 时按匝道处理。
- 真实 DWG：通过 `DWGProfile.viaduct_layer_keywords` 和 `DWGProfile.ramp_layer_keywords` 配置识别关键词。
- 建筑功能文本包含 `居住`、`住宅`、`学校`、`医院`、`幼儿园`、`托儿所`、`宿舍`、`疗养` 时按敏感建筑组取值，否则按其他建筑组取值。
- 审查结果复用 `ReviewAgent` 的临接对象筛选、距离计算、合规判定和报告输出，不另写单独脚本。

### 5.6 实际退让距离

几何计算代码：

```text
app/geometry.py
```

计算公式：

```text
实际让距 = 建筑轮廓边界 到 道路红线面域边界 的最短距离
```

允许误差：

```text
±0.1m
```

符合题目中允许 `±0.1m` 误差的评分要求。

---

## 6. CAD 输入处理

### 6.1 标准 DXF 解析

解析器：

```text
app/parser.py
```

适用于：

```text
test_site_01.dxf
test_site_02.dxf
```

图层/标注约定：

| 对象 | 解析方式 |
|---|---|
| 道路红线 | `ROAD_REDLINE` 图层 |
| 道路中心线 | `ROAD_CENTERLINE` 图层 |
| 道路宽度 | 文字标注，例如 `道路A W=24m` |
| 建筑 | `BUILDING_LOW`、`BUILDING_MULTI`、`BUILDING_HIGH` |
| 建筑高度 | XDATA `HZPLAN/1040` 或文字 `H=18m` |
| 建筑名称 | XDATA `HZPLAN/1000` 或附近文字 |

支持：

- 闭合道路红线面域。
- 未闭合道路红线边线。
- 道路中心线 + 宽度构造道路面域。
- TEXT / MTEXT 文本识别。
- 建筑文字和 XDATA 双通道提取。

### 6.2 DWG 自动转换

转换器：

```text
app/converter.py
```

流程：

```text
DWG 输入
  ↓
查找 ODA File Converter
  ↓
自动转换为 DXF
  ↓
进入 DWG 专用解析器
```

如果系统未自动找到 ODA，可设置：

```powershell
$env:ODA_FILE_CONVERTER="C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"
```

报告和 Web 页面会显示转换过程，例如：

```text
接收文件：test_site_03.dwg
识别为 DWG 文件：准备自动转换为 DXF。
转换工具：...
执行 DWG→DXF 转换，用时 0.7171s。
转换成功：test_site_03.dxf
```

### 6.3 DWG 专用解析

解析器：

```text
app/dwg_parser.py
```

配置入口：

```text
app/dwg_profile.py
```

DWG 分支的算法逻辑：

1. ODA 将 DWG 转成 DXF。
2. `ParseAgent` 判断该图纸来自 DWG 转换，进入 `parse_converted_dwg_dxf()`。
3. 读取 `app/dwg_profile.py` 中当前模式的图层配置。
4. 按用户提供的颜色/图层分类抽取审查对象：
   - 蓝灰色道路系统：`G_DRIV_ROAD`、`G-ROAD-CNTR`、`G-ROAD-园区`
   - 红色市政道路边界：`G-ROAD-市政`
   - 红色用地/权属红线：`G-SITE-PROP`、`G_SITE_REDL`、`总图-征地红线`
   - 建筑主体：`G-BLDG-HIGH`、`G-BLDG-MULT`，`G-BLDG-OTLN` 仅作细节/块参照兜底
   - 高架/轨道/匝道：按 `viaduct_layer_keywords`、`ramp_layer_keywords` 识别并进入表3-3审查
5. 排除注释、标注、轴网、绿化、停车、填充、屋面、地下、楼梯、玻璃幕墙、设施细节等非审查图层。
6. 构造道路面域，提取建筑轮廓。
7. DWG 坐标按毫米级总图坐标处理，距离输出时用 `unit_scale=0.001` 换算为米。
8. 交给 `ReviewAgent` 执行表 3-2、第 3 款和表 3-3 审查。

需要自己修改 DWG 识别时，优先改 `app/dwg_profile.py`，不要直接改算法：

| 想调整的内容 | 修改字段 |
|---|---|
| 建筑主体图层 | `building_high_layers`、`building_multi_layers`、`building_polyline_layers`、`building_insert_layers` |
| 蓝灰道路图层 | `road_layer_keywords` |
| 红色市政道路边界 | `municipal_boundary_keywords` |
| 亮天蓝控制线 | `blue_boundary_keywords` |
| 红线/控制边界图层 | `redline_layer_keywords` |
| 高架图层 | `viaduct_layer_keywords` |
| 匝道图层 | `ramp_layer_keywords` |
| 高压线图层 | `powerline_layer_keywords` |
| 明确不要识别的图层 | `ignore_layers` |
| 标注/注释关键词 | `annotation_keywords` |
| 建筑面积过滤 | `min_building_area`、`max_building_area` |
| 道路候选数量 | `max_review_roads` |
| 是否四象限分片 | `split_quadrants` |

注意：`G-ROAD-市政` 表示市政道路边界，可参与道路红线构造；`G-SITE-PROP`、`G_SITE_REDL`、`总图-征地红线` 表示用地/权属红线，只作为辅助筛选，不直接当道路中心线，避免道路面域跑偏。

---

## 7. DWG 严格审查模式

当前 DWG 解析只保留一个模式：`strict` 严格审查模式。Web 和 CLI 不再提供平衡模式、完整模式选择，避免不同模式生成的对象数量和报告结论不一致。

用途：输出较干净、适合最终报告演示的主要对象。

特点：

- 严格按颜色分类图层表识别道路、红线、市政道路边界和建筑主体。
- 蓝灰色 `G_DRIV_ROAD/G-ROAD-CNTR/G-ROAD-园区` 为道路系统，红色 `G-ROAD-市政` 为市政道路边界。
- 红色 `G-SITE-PROP/G_SITE_REDL/总图-征地红线` 为用地/权属控制线，只辅助筛选。
- 红色 `G-BLDG-HIGH` 识别为高层建筑，紫色 `G-BLDG-MULT` 识别为多层建筑。
- 强过滤小构件、注释、填充、绿化、停车、屋面、地下室、楼梯、玻璃幕墙、设施细节等非审查对象。
- 对同一建筑的内外重复轮廓进行去重。
- 道路候选数量受控，避免真实 DWG 道路碎线造成报告膨胀。
- 可能漏掉部分真实对象；如报告出现低置信度提示，应人工复核图层配置。

命令行运行无需再传 `--dwg-mode`：

```bash
python main.py test_site_03.dwg --output outputs
```

---

## 8. Web 运行方式

启动：

```bash
python -m app.web
```

浏览器打开：

```text
http://127.0.0.1:5000
```

Web 功能：

- 上传 `DXF` / `DWG`。
- DWG 固定使用严格审查模式。
- 显示处理过程。
- 显示道路数量、建筑数量、合规/不合规数量。
- 显示 `t_convert / t_parse / t_review / t_render / t_total`。
- 预览 HTML 报告。
- 打开标注图和 timing JSON。

Web 上传目录：

```text
uploads/<job_id>/
```

Web 输出目录：

```text
outputs/web/<job_id>/
```

---

## 9. 命令行运行方式

### 9.1 安装依赖

建议 Python 版本：`3.11+`。

```bash
pip install -r requirements.txt
```

Windows 虚拟环境示例：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 9.2 自动扫描当前目录 CAD 文件

```bash
python main.py
```

### 9.3 指定文件运行

```bash
python main.py test_site_01.dxf test_site_02.dxf --output outputs
```

### 9.4 指定 DWG 模式运行

```bash
python main.py test_site_03.dwg --output outputs
```

---

## 10. 输出报告要求对应说明

### 10.1 报告格式

题目允许：HTML、PDF、Markdown + 图片。

本项目选择：

```text
HTML 报告 + 独立 PNG 标注图片 + timing JSON
```

### 10.2 报告内容

| 题目要求 | 当前实现 |
|---|---|
| 项目概览：道路数量、建筑数量、审查依据 | 已实现 |
| 逐栋审查明细表：建筑名称、类型、高度、临接道路、实际让距、理论让距、判定结果 | 已实现，并额外输出依据链 |
| 总平面标注图：合规绿色，不合规红色，标注实际/理论让距 | 已实现。建筑用绿色/红色表达，问题清单列出实际/理论让距 |
| 审查结论摘要：合规/不合规建筑数量、问题清单 | 已实现 |
| 审查速度上报：`t_parse / t_review / t_render / t_total` | 已实现，并额外输出 `t_convert` |

### 10.3 输出文件

每张图纸输出：

| 文件 | 说明 |
|---|---|
| `*_report.html` | 图文审查报告 |
| `*_annotation.png` | 总平面标注图 |
| `*_timing.json` | 单图纸耗时日志 |

批量运行额外输出：

```text
outputs/speed_summary.json
```

---

## 11. 标注图说明

标注图由 `app/renderer.py` 生成。

图面规则：

| 图形 | 含义 |
|---|---|
| 绿色建筑 | 合规建筑 |
| 红色建筑 | 不合规建筑 |
| 浅蓝色面域 | 道路红线面域 |
| 红色边界 | 道路红线边界 |
| 绿色虚线 | 道路中心线 |
| 建筑短标签 | `B1`、`B2` 等建筑编号 |
| 右侧问题清单 | 不合规对象、临接道路、实际/理论让距 |

说明：为避免标注图拥挤，建筑内部只保留短标签，实际/理论让距统一放入右侧问题清单和逐栋明细表中。

---

## 12. 速度日志

速度字段：

| 字段 | 含义 |
|---|---|
| `t_convert` | DWG 转 DXF 耗时；DXF 输入时通常为 0 |
| `t_parse` | CAD 解析耗时 |
| `t_review` | 规范推理和合规判定耗时 |
| `t_render` | 报告和标注图生成耗时 |
| `t_total` | 总耗时 |

题目要求的字段均包含：

```text
t_parse
t_review
t_render
t_total
```

---

## 13. 项目结构

```text
二轮题测/
├─ app/
│  ├─ agent.py          # LangGraph Agent 编排
│  ├─ cli.py            # 命令行入口
│  ├─ converter.py      # DWG 自动转换
│  ├─ dwg_parser.py     # DWG 专用解析器
│  ├─ dwg_profile.py    # DWG 严格模式图层配置
│  ├─ geometry.py       # 几何计算
│  ├─ models.py         # 数据模型
│  ├─ parser.py         # 标准 DXF 解析器
│  ├─ renderer.py       # 报告和标注图渲染
│  ├─ reviewer.py       # 审查逻辑
│  ├─ rules.py          # 规则引擎
│  └─ web.py            # Web 上传界面
├─ tests/
│  ├─ test_geometry_and_reviewer.py
│  └─ test_rules.py
├─ outputs/             # 报告输出目录
├─ uploads/             # Web 上传目录
├─ main.py              # CLI 入口
├─ requirements.txt
└─ README.md
```

---

## 14. 单元测试与断言验证

运行：

```bash
python -m pytest -q
```

测试覆盖：

- 道路宽度分档。
- Q 值计算。
- 表 3-2 查询。
- 交叉口规则。
- 建筑到道路红线边界距离。
- 完整合规判定链路。

当前验证结果：

```text
7 passed
```

---

## 15. 核心代码可解释性

题目要求候选人必须能够解释核心代码。本项目核心设计如下：

| 文件 | 可解释点 |
|---|---|
| `app/agent.py` | Agent 拆分、LangGraph 节点与边、上下文状态传递 |
| `app/converter.py` | DXF/DWG 输入分流、ODA 转换、转换过程日志 |
| `app/parser.py` | 标准 DXF 图层解析、文字解析、道路面域构造 |
| `app/dwg_parser.py` | 真实 DWG 的块参照、填充、图层候选和严格模式解析 |
| `app/rules.py` | 表 3-2、Q 值、建筑类别、交叉口控制值 |
| `app/reviewer.py` | 临接道路筛选、实际让距计算、合规判定 |
| `app/renderer.py` | 标注图、HTML 报告、timing JSON 输出 |

---

## 16. 交付物清单对应说明

| 题目交付物 | 当前项目对应内容 |
|---|---|
| 源代码完整项目目录 | 当前仓库全部文件 |
| 依赖文件 | `requirements.txt` |
| README 运行说明、Agent 架构、技术选型理由 | 本文件 |
| 三份图纸完整审查报告 | 运行 `python main.py` 或 Web 上传后生成到 `outputs/` |
| 速度测试日志 | `*_timing.json` 和 `speed_summary.json` |
| 演示视频/动图 | 未包含，可选项 |

生成三份图纸报告的推荐命令：

```bash
python main.py test_site_01.dxf test_site_02.dxf test_site_03.dwg --output outputs
```

如果想查看 DWG 完整解析覆盖情况：

```bash
python main.py test_site_03.dwg --output outputs
```

---

## 17. 已知限制

1. `test_site_03.dwg` 是真实图纸，图层复杂，系统会输出解析置信度。若道路红线识别置信度低，结论需人工复核。
2. DWG 转 DXF 后可能出现中文字体乱码，因此 DWG 分支优先依赖几何图元、块参照和 HATCH 填充，不完全依赖文字。
3. DWG 当前固定使用严格审查模式；若真实图纸缺少关键图层，应优先调整 `DWGProfile` 图层白名单，而不是切换解析模式。
4. 本项目按题目核心要求实现表 3-2 和第 3 款，并支持可选加分项表 3-3 高架/匝道退让、表 3-4 高压线退让。
5. 若要进一步提高真实 DWG 准确度，建议增加 Web 图层配置面板，由用户指定建筑轮廓层、道路红线层、中心线层和忽略层。

---

## 18. 快速命令汇总

安装依赖：

```bash
pip install -r requirements.txt
```

运行测试：

```bash
python -m pytest -q
```

启动 Web：

```bash
python -m app.web
```

运行 DXF：

```bash
python main.py test_site_01.dxf --output outputs
```

运行三份图纸：

```bash
python main.py test_site_01.dxf test_site_02.dxf test_site_03.dwg --output outputs
```

运行 DWG 严格模式：

```bash
python main.py test_site_03.dwg --output outputs
```
