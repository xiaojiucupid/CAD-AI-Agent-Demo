from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from app.agent import ReviewWorkflow
from app.analysis import analyze_cad_file, save_analysis_json

# BASE_DIR: 项目根目录。
BASE_DIR = Path(__file__).resolve().parent.parent
# UPLOAD_DIR: Web 上传文件保存目录。
UPLOAD_DIR = BASE_DIR / "uploads"
# OUTPUT_DIR: Web 报告输出目录，每次上传使用独立 job_id 子目录。
OUTPUT_DIR = BASE_DIR / "outputs" / "web"
# ALLOWED_SUFFIXES: 允许上传的 CAD 文件后缀。
ALLOWED_SUFFIXES = {".dxf", ".dwg"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 80 * 1024 * 1024


PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>建筑退让道路红线智能审查</title>
  <style>
    :root { color-scheme: light; --primary:#2563eb; --primary2:#1d4ed8; --bg:#eef4ff; --card:#ffffff; --text:#172033; --muted:#64748b; --ok:#16a34a; --bad:#dc2626; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif; background: radial-gradient(circle at top left, #dbeafe 0, #eef4ff 32%, #f8fafc 80%); color:var(--text); min-height:100vh; }
    .shell { max-width:1180px; margin:0 auto; padding:42px 22px 60px; }
    .hero { display:grid; grid-template-columns:minmax(0,1.12fr) minmax(360px,.88fr); gap:28px; align-items:start; }
    .title-card, .upload-card, .result-card { background:rgba(255,255,255,.92); border:1px solid rgba(148,163,184,.28); border-radius:28px; box-shadow:0 24px 80px rgba(37,99,235,.14); }
    .title-card { padding:42px; position:relative; overflow:hidden; min-height:360px; }
    .title-card:after { content:""; position:absolute; width:230px; height:230px; border-radius:999px; background:linear-gradient(135deg, rgba(37,99,235,.16), rgba(14,165,233,.08)); right:-70px; top:-70px; }
    .badge { display:inline-flex; gap:8px; align-items:center; padding:7px 12px; border-radius:999px; background:#dbeafe; color:#1e40af; font-weight:700; font-size:13px; }
    h1 { margin:24px 0 16px; font-size:42px; line-height:1.15; letter-spacing:-.6px; }
    .lead { font-size:17px; color:var(--muted); line-height:1.8; max-width:620px; }
    .features { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin-top:30px; }
    .feature { background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:14px; font-size:14px; color:#334155; min-width:0; }
    .upload-card { padding:30px; min-height:360px; display:flex; flex-direction:column; justify-content:center; overflow:hidden; }
    #uploadForm { width:100%; }
    .drop { display:block; width:100%; border:2px dashed #93c5fd; border-radius:24px; padding:34px 20px; text-align:center; background:linear-gradient(180deg,#eff6ff,#fff); transition:.2s; cursor:pointer; }
    .drop.drag, .drop:hover { border-color:var(--primary); box-shadow:0 16px 35px rgba(37,99,235,.12); }
    .drop strong { display:block; font-size:20px; margin-bottom:10px; white-space:normal; }
    .drop span { display:block; color:var(--muted); font-size:14px; line-height:1.6; }
    input[type=file] { display:none; }
    .file-name { margin:16px 0; color:#334155; font-size:14px; min-height:22px; }
    button { width:100%; border:0; border-radius:16px; padding:15px 18px; font-size:16px; font-weight:800; color:white; background:linear-gradient(135deg,var(--primary),#0ea5e9); cursor:pointer; box-shadow:0 14px 30px rgba(37,99,235,.25); }
    button:disabled { cursor:not-allowed; opacity:.55; box-shadow:none; }
    .hint { margin-top:16px; font-size:13px; color:var(--muted); line-height:1.7; }
    .mode-box { margin-top:16px; padding:14px; border:1px solid #dbeafe; border-radius:16px; background:#f8fbff; color:#334155; font-size:14px; line-height:1.7; }
    .mode-box b { display:block; margin-bottom:6px; color:#1e3a8a; }
    .result-card { margin-top:28px; padding:28px; display:none; }
    .result-head { display:flex; justify-content:space-between; gap:16px; align-items:center; border-bottom:1px solid #e2e8f0; padding-bottom:18px; margin-bottom:20px; }
    .status { font-weight:900; font-size:20px; }
    .status.ok { color:var(--ok); } .status.bad { color:var(--bad); }
    .metrics { display:grid; grid-template-columns:repeat(5,1fr); gap:14px; margin:20px 0; }
    .metric { background:#f8fafc; border:1px solid #e2e8f0; border-radius:16px; padding:14px; }
    .metric small { display:block; color:var(--muted); margin-bottom:6px; } .metric b { font-size:20px; }
    .links { display:flex; flex-wrap:wrap; gap:12px; margin-top:18px; }
    .links a { text-decoration:none; color:white; background:#1e293b; padding:11px 15px; border-radius:12px; font-weight:700; font-size:14px; }
    .links a.secondary { background:#2563eb; }
    .preview { margin-top:20px; border:1px solid #e2e8f0; border-radius:18px; overflow:hidden; background:#fff; }
    iframe { width:100%; min-height:560px; border:0; }
    .error { margin-top:18px; padding:14px; background:#fef2f2; color:#991b1b; border:1px solid #fecaca; border-radius:14px; display:none; }
    .spinner { display:none; margin-top:18px; color:#1e40af; font-weight:700; }
    @media (max-width: 980px) { .hero { grid-template-columns:1fr; } h1 { font-size:32px; } .title-card,.upload-card { min-height:auto; } .features,.metrics { grid-template-columns:1fr; } }
    @media (max-width: 520px) { .shell { padding:22px 12px 40px; } .title-card,.upload-card,.result-card { border-radius:20px; padding:22px; } .drop { padding:26px 14px; } }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <div class="title-card">
        <div class="badge">AI Agent · CAD 审查 Demo</div>
        <h1>建筑退让道路红线智能审查</h1>
        <p class="lead">上传 DXF/DWG 总平面图，系统将通过 Agent 工作流完成图纸解析、规则推理、合规判定与 HTML 图文报告生成，并返回速度统计。</p>
        <div class="features">
          <div class="feature">Parse Agent<br><b>道路/建筑抽取</b></div>
          <div class="feature">Review Agent<br><b>表 3-2 + 交叉口</b></div>
          <div class="feature">Report Agent<br><b>标注图与结论</b></div>
        </div>
      </div>
      <div class="upload-card">
        <form id="uploadForm">
          <label class="drop" id="dropZone" for="fileInput">
            <strong>点击或拖拽上传 CAD 文件</strong>
            <span>支持 .dxf；.dwg 将自动转换为 .dxf</span>
          </label>
          <input id="fileInput" type="file" name="file" accept=".dxf,.dwg">
          <div class="mode-box">
            <b>DWG 解析模式</b>
            当前仅使用严格审查模式：按图层白名单抽取道路、红线和建筑主体，减少真实 DWG 误识别。
          </div>
          <div class="file-name" id="fileName">尚未选择文件</div>
          <button id="submitBtn" type="submit" disabled>开始解析并生成报告</button>
        </form>
        <div class="spinner" id="spinner">正在审查中，请稍候...</div>
        <div class="error" id="errorBox"></div>
        <p class="hint">说明：上传文件会保存到本地 uploads 目录，报告输出到 outputs/web。DWG 自动转换依赖 ODA File Converter；若未安装，会在转换过程里给出文字提示。</p>
      </div>
    </section>

    <section class="result-card" id="resultCard">
      <div class="result-head">
        <div>
          <div class="status" id="statusText">审查完成</div>
          <div id="overviewText" style="color:#64748b;margin-top:6px"></div>
        </div>
      </div>
      <h3>处理过程</h3>
      <ol id="processSteps" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:16px;padding:16px 16px 16px 36px;color:#334155;line-height:1.8"></ol>
      <div class="metrics">
        <div class="metric"><small>t_convert</small><b id="tConvert">-</b></div>
        <div class="metric"><small>t_parse</small><b id="tParse">-</b></div>
        <div class="metric"><small>t_review</small><b id="tReview">-</b></div>
        <div class="metric"><small>t_render</small><b id="tRender">-</b></div>
        <div class="metric"><small>t_total</small><b id="tTotal">-</b></div>
      </div>
      <div class="links" id="artifactLinks"></div>
      <div class="preview"><iframe id="reportFrame" title="审查报告预览"></iframe></div>
    </section>
  </main>
<script>
const fileInput = document.getElementById('fileInput');
const fileName = document.getElementById('fileName');
const submitBtn = document.getElementById('submitBtn');
const form = document.getElementById('uploadForm');
const spinner = document.getElementById('spinner');
const errorBox = document.getElementById('errorBox');
const resultCard = document.getElementById('resultCard');
const dropZone = document.getElementById('dropZone');

function setFile(file) { fileName.textContent = file ? file.name : '尚未选择文件'; submitBtn.disabled = !file; }
fileInput.addEventListener('change', () => setFile(fileInput.files[0]));
['dragenter','dragover'].forEach(evt => dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.add('drag'); }));
['dragleave','drop'].forEach(evt => dropZone.addEventListener(evt, e => { e.preventDefault(); dropZone.classList.remove('drag'); }));
dropZone.addEventListener('drop', e => { fileInput.files = e.dataTransfer.files; setFile(fileInput.files[0]); });

function seconds(v) { return `${Number(v || 0).toFixed(4)}s`; }
form.addEventListener('submit', async e => {
  e.preventDefault();
  if (!fileInput.files[0]) return;
  errorBox.style.display = 'none'; resultCard.style.display = 'none'; spinner.style.display = 'block'; submitBtn.disabled = true;
  const data = new FormData(); data.append('file', fileInput.files[0]);
  try {
    const resp = await fetch('/api/review', { method:'POST', body:data });
    const json = await resp.json();
    if (!resp.ok || !json.ok) throw new Error(json.error || '审查失败');
    document.getElementById('statusText').textContent = json.failed_buildings > 0 ? '发现不合规问题' : '全部合规';
    document.getElementById('statusText').className = 'status ' + (json.failed_buildings > 0 ? 'bad' : 'ok');
    document.getElementById('overviewText').textContent = `道路 ${json.road_count} 条，建筑 ${json.building_count} 栋，合规 ${json.passed_buildings} 栋，不合规 ${json.failed_buildings} 栋`;
    const allSteps = [...(json.conversion_steps || []), ...(json.parse_warnings || [])];
    document.getElementById('processSteps').innerHTML = allSteps.map(step => `<li>${step}</li>`).join('') || '<li>DXF 直接解析，无格式转换。</li>';
    document.getElementById('tConvert').textContent = seconds(json.timing.t_convert);
    document.getElementById('tParse').textContent = seconds(json.timing.t_parse);
    document.getElementById('tReview').textContent = seconds(json.timing.t_review);
    document.getElementById('tRender').textContent = seconds(json.timing.t_render);
    document.getElementById('tTotal').textContent = seconds(json.timing.t_total);
    const hasGroups = json.artifact_groups && json.artifact_groups.length > 0;
    const groupLinks = (json.artifact_groups || []).map(group => `<a class="secondary" href="${group.report_url}" target="_blank">${group.title}报告</a><a href="${group.image_url}" target="_blank">${group.title}标注图</a>`).join('');
    const singleLinks = json.report_url ? `<a class="secondary" href="${json.report_url}" target="_blank">打开 HTML 报告</a><a href="${json.image_url}" target="_blank">查看标注图</a><a href="${json.timing_url}" target="_blank">查看耗时 JSON</a>` : '';
    document.getElementById('artifactLinks').innerHTML = hasGroups ? groupLinks : singleLinks;
    document.getElementById('reportFrame').src = hasGroups ? json.artifact_groups[0].report_url : (json.report_url || '');
    resultCard.style.display = 'block';
  } catch (err) {
    errorBox.textContent = err.message; errorBox.style.display = 'block';
  } finally {
    spinner.style.display = 'none'; submitBtn.disabled = !fileInput.files[0];
  }
});
</script>
</body>
</html>
"""


ANALYSIS_PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DXF/DWG 结构化图纸分析</title>
  <style>
    :root { --primary:#0f766e; --bg:#ecfeff; --card:#ffffff; --text:#0f172a; --muted:#64748b; --line:#dbeafe; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; background:linear-gradient(135deg,#ecfeff,#f8fafc 62%,#eef2ff); color:var(--text); min-height:100vh; }
    .shell { max-width:1180px; margin:0 auto; padding:38px 20px 56px; }
    .hero { display:grid; grid-template-columns:1fr 420px; gap:24px; align-items:start; }
    .card { background:rgba(255,255,255,.94); border:1px solid rgba(148,163,184,.32); border-radius:26px; box-shadow:0 22px 70px rgba(15,118,110,.12); padding:30px; }
    h1 { margin:14px 0 14px; font-size:38px; line-height:1.16; letter-spacing:-.4px; }
    .badge { display:inline-flex; padding:7px 12px; border-radius:999px; background:#ccfbf1; color:#115e59; font-weight:800; font-size:13px; }
    .lead { color:var(--muted); line-height:1.85; font-size:16px; }
    .points { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:24px; }
    .point { border:1px solid #e2e8f0; background:#f8fafc; border-radius:16px; padding:14px; color:#334155; font-size:14px; }
    .drop { display:block; border:2px dashed #5eead4; border-radius:22px; padding:34px 16px; text-align:center; background:linear-gradient(180deg,#f0fdfa,#fff); cursor:pointer; }
    .drop strong { display:block; font-size:19px; margin-bottom:10px; }
    input[type=file] { display:none; }
    .file-name,.hint { color:var(--muted); font-size:14px; line-height:1.7; margin-top:14px; }
    .mode-box { margin-top:16px; padding:14px; border:1px solid #ccfbf1; border-radius:16px; background:#f8fffe; color:#334155; font-size:14px; line-height:1.7; }
    .mode-box b,.section-title { color:#134e4a; }
    button { width:100%; margin-top:18px; border:0; border-radius:16px; padding:15px 18px; color:white; font-weight:900; font-size:16px; cursor:pointer; background:linear-gradient(135deg,#0f766e,#0891b2); box-shadow:0 14px 30px rgba(15,118,110,.22); }
    button:disabled { opacity:.55; cursor:not-allowed; box-shadow:none; }
    .result { display:none; margin-top:24px; }
    .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:18px 0; }
    .metric { border:1px solid #e2e8f0; background:#f8fafc; border-radius:16px; padding:14px; }
    .metric small { display:block; color:var(--muted); margin-bottom:7px; } .metric b { font-size:22px; }
    table { width:100%; border-collapse:collapse; margin-top:12px; overflow:hidden; border-radius:14px; }
    th,td { text-align:left; padding:10px 12px; border-bottom:1px solid #e2e8f0; font-size:14px; vertical-align:top; } th { background:#f1f5f9; color:#334155; }
    .two { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
    .links { display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }
    .links a { text-decoration:none; color:white; background:#0f172a; padding:10px 14px; border-radius:12px; font-weight:800; font-size:14px; }
    .error { display:none; margin-top:16px; padding:13px; border-radius:14px; background:#fef2f2; color:#991b1b; border:1px solid #fecaca; }
    .spinner { display:none; color:#0f766e; font-weight:800; margin-top:16px; }
    @media (max-width: 980px) { .hero,.two { grid-template-columns:1fr; } .points,.grid { grid-template-columns:1fr; } h1 { font-size:30px; } }
  </style>
</head>
<body>
<main class="shell">
  <section class="hero">
    <div class="card">
      <span class="badge">CAD Structured Analysis</span>
      <h1>DXF/DWG 结构化图纸分析</h1>
      <p class="lead">该页面不做截图 OCR 或视觉目标检测，而是直接读取 CAD 文件中的坐标、图层、图元类型、文字标注和可解析语义对象，输出当前图纸的结构化汇总。</p>
      <div class="points"><div class="point">图元类型<br><b>LINE / PLINE / TEXT</b></div><div class="point">图层统计<br><b>按 layer 汇总</b></div><div class="point">对象语义<br><b>道路 / 建筑 / 标注</b></div></div>
    </div>
    <div class="card">
      <form id="analysisForm">
        <label class="drop" for="analysisFile"><strong>上传当前 DXF/DWG 图</strong><span>DWG 自动转换后再结构化读取</span></label>
        <input id="analysisFile" type="file" name="file" accept=".dxf,.dwg">
        <div class="mode-box"><b>DWG 分析模式</b>当前仅使用严格审查模式，统一按图层白名单进行结构化读取。</div>
        <div class="file-name" id="analysisFileName">尚未选择文件</div>
        <button id="analysisSubmit" type="submit" disabled>开始结构化分析</button>
      </form>
      <div class="spinner" id="analysisSpinner">正在读取图纸结构...</div>
      <div class="error" id="analysisError"></div>
      <p class="hint">提示：如需审查退让规则仍使用首页；本页面用于快速确认图纸中到底有哪些图层、实体和候选道路/建筑。</p>
    </div>
  </section>
  <section class="card result" id="analysisResult">
    <h2>分析汇总</h2>
    <div class="grid"><div class="metric"><small>总图元</small><b id="mEntities">-</b></div><div class="metric"><small>图层数</small><b id="mLayers">-</b></div><div class="metric"><small>道路候选</small><b id="mRoads">-</b></div><div class="metric"><small>建筑候选</small><b id="mBuildings">-</b></div></div>
    <div id="basicInfo" class="hint"></div><div class="links" id="analysisLinks"></div>
    <div class="two"><div><h3 class="section-title">图元类型 Top</h3><table><thead><tr><th>类型</th><th>数量</th></tr></thead><tbody id="typeRows"></tbody></table></div><div><h3 class="section-title">图层 Top</h3><table><thead><tr><th>图层</th><th>数量</th></tr></thead><tbody id="layerRows"></tbody></table></div></div>
    <h3 class="section-title">道路/线性控制对象</h3><table><thead><tr><th>名称</th><th>类型</th><th>宽度/电压</th><th>来源层</th></tr></thead><tbody id="roadRows"></tbody></table>
    <h3 class="section-title">建筑对象</h3><table><thead><tr><th>名称</th><th>类型</th><th>高度</th><th>面积</th><th>来源层</th></tr></thead><tbody id="buildingRows"></tbody></table>
    <h3 class="section-title">文字样本</h3><table><thead><tr><th>类型</th><th>图层</th><th>内容</th></tr></thead><tbody id="textRows"></tbody></table>
  </section>
</main>
<script>
const input = document.getElementById('analysisFile'); const nameBox = document.getElementById('analysisFileName'); const btn = document.getElementById('analysisSubmit'); const formA = document.getElementById('analysisForm'); const err = document.getElementById('analysisError'); const spinnerA = document.getElementById('analysisSpinner'); const resultA = document.getElementById('analysisResult');
input.addEventListener('change', () => { const f=input.files[0]; nameBox.textContent=f?f.name:'尚未选择文件'; btn.disabled=!f; });
const rows = (obj, limit=12) => Object.entries(obj || {}).slice(0, limit).map(([k,v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('') || '<tr><td colspan="2">无</td></tr>';
formA.addEventListener('submit', async e => { e.preventDefault(); if(!input.files[0]) return; err.style.display='none'; resultA.style.display='none'; spinnerA.style.display='block'; btn.disabled=true; const data=new FormData(); data.append('file', input.files[0]); try { const resp=await fetch('/api/analyze',{method:'POST',body:data}); const json=await resp.json(); if(!resp.ok || !json.ok) throw new Error(json.error || '分析失败'); const r=json.report; document.getElementById('mEntities').textContent=r.entity_summary.total_entities; document.getElementById('mLayers').textContent=Object.keys(r.entity_summary.by_layer || {}).length; document.getElementById('mRoads').textContent=r.semantic_summary.road_count; document.getElementById('mBuildings').textContent=r.semantic_summary.building_count; document.getElementById('basicInfo').textContent=`解析模式：${r.semantic_summary.parse_mode}；置信度：${r.semantic_summary.confidence}；单位换算：${r.semantic_summary.unit_scale}；耗时：${Number(r.elapsed_seconds).toFixed(4)}s`; document.getElementById('analysisLinks').innerHTML=`<a href="${json.json_url}" target="_blank">打开 JSON 汇总</a>`; document.getElementById('typeRows').innerHTML=rows(r.entity_summary.by_type); document.getElementById('layerRows').innerHTML=rows(r.entity_summary.by_layer); document.getElementById('roadRows').innerHTML=(r.semantic_summary.roads || []).map(x=>`<tr><td>${x.name}</td><td>${x.kind}</td><td>${x.width_or_voltage}</td><td>${x.source_layer}</td></tr>`).join('') || '<tr><td colspan="4">未识别到道路/线性控制对象</td></tr>'; document.getElementById('buildingRows').innerHTML=(r.semantic_summary.buildings || []).map(x=>`<tr><td>${x.name}</td><td>${x.type}</td><td>${x.height}</td><td>${Number(x.area || 0).toFixed(2)}</td><td>${x.layer}</td></tr>`).join('') || '<tr><td colspan="5">未识别到建筑对象</td></tr>'; document.getElementById('textRows').innerHTML=(r.entity_summary.text_samples || []).slice(0,20).map(x=>`<tr><td>${x.type}</td><td>${x.layer}</td><td>${x.text}</td></tr>`).join('') || '<tr><td colspan="3">无文字样本</td></tr>'; resultA.style.display='block'; } catch(ex) { err.textContent=ex.message; err.style.display='block'; } finally { spinnerA.style.display='none'; btn.disabled=!input.files[0]; } });
</script>
</body>
</html>
"""


@app.get("/")
def index() -> str:
    """Web 首页：返回上传表单和报告预览页面。"""

    return render_template_string(PAGE_TEMPLATE)


@app.get("/analysis")
def analysis_page() -> str:
    """结构化 CAD 分析页面：不做视觉识别，只汇总原生 DXF/DWG 数据。"""

    return render_template_string(ANALYSIS_PAGE_TEMPLATE)


@app.post("/api/review")
def review_upload():
    """上传 CAD 并触发 Agent 审查流程，返回报告 URL 和统计信息。"""

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "error": "请先选择 DXF 或 DWG 文件。"}), 400

    # original_name: 经过安全处理后的文件名，避免路径穿越。
    original_name = secure_filename(uploaded.filename) or "drawing.dxf"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return jsonify({"ok": False, "error": "仅支持上传 .dxf 或 .dwg 文件。"}), 400

    # dwg_mode: DWG 解析已统一为严格模式。
    dwg_mode = "strict"

    # job_id: 本次上传任务 ID，用于隔离不同用户/不同图纸的文件。
    job_id = uuid4().hex[:12]
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_upload_dir / original_name
    uploaded.save(input_path)

    try:
        # workflow: LangGraph Agent 编排器，内部执行 Convert -> Parse -> Review -> Report。
        workflow = ReviewWorkflow()
        ctx = workflow.run(input_path, job_output_dir, dwg_mode=dwg_mode)
    except ValueError as exc:
        shutil.rmtree(job_output_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": str(exc)}), 422
    except Exception as exc:
        shutil.rmtree(job_output_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": f"审查失败：{exc}"}), 500

    if ctx.drawing is None or ctx.results is None or ctx.artifacts is None:
        return jsonify({"ok": False, "error": "审查流程未返回完整结果。"}), 500

    def artifact_url(kind: str) -> str:
        """把报告产物路径转换为浏览器可访问的 URL。"""

        path = ctx.artifacts[kind]
        return url_for("serve_artifact", job_id=job_id, filename=path.name)

    if ctx.conversion and ctx.conversion.converted:
        default_buildings = ctx.drawing.scenario_buildings.get("site_prop_redline", ctx.drawing.buildings)
        building_names = {building.name for building in default_buildings}
        failed_buildings = {result.building_name for result in ctx.results if not result.passed}
        passed_buildings = len(building_names - failed_buildings)
        artifact_groups = []
        if "site_prop_redline_html" in ctx.artifacts and "site_prop_redline_image" in ctx.artifacts:
            artifact_groups.append(
                {
                    "key": "site_prop_redline",
                    "title": "第二组",
                    "report_url": artifact_url("site_prop_redline_html"),
                    "image_url": artifact_url("site_prop_redline_image"),
                    "timing_url": artifact_url("site_prop_redline_timing") if "site_prop_redline_timing" in ctx.artifacts else artifact_url("timing"),
                }
            )
        if "building_site_open_redline_html" in ctx.artifacts and "building_site_open_redline_image" in ctx.artifacts:
            artifact_groups.append(
                {
                    "key": "building_site_open_redline",
                    "title": "第三组",
                    "report_url": artifact_url("building_site_open_redline_html"),
                    "image_url": artifact_url("building_site_open_redline_image"),
                    "timing_url": artifact_url("building_site_open_redline_timing") if "building_site_open_redline_timing" in ctx.artifacts else artifact_url("timing"),
                }
            )
        payload = {
            "ok": True,
            "job_id": job_id,
            "road_count": len(ctx.drawing.scenario_core_redlines.get("site_prop_redline", ctx.drawing.roads)),
            "building_count": len(default_buildings),
            "passed_buildings": passed_buildings,
            "failed_buildings": len(failed_buildings),
            "timing": {
                "t_convert": ctx.timing.t_convert,
                "t_parse": ctx.timing.t_parse,
                "t_review": ctx.timing.t_review,
                "t_render": ctx.timing.t_render,
                "t_total": ctx.timing.t_total,
            },
            "conversion_steps": ctx.conversion.steps if ctx.conversion else [],
            "dwg_mode": dwg_mode,
            "parse_mode": ctx.drawing.parse_mode,
            "confidence": ctx.drawing.confidence,
            "parse_warnings": ctx.drawing.parse_warnings,
            "artifact_groups": artifact_groups,
        }
        return jsonify(payload)

    building_names = {building.name for building in ctx.drawing.buildings}
    failed_buildings = {result.building_name for result in ctx.results if not result.passed}
    passed_buildings = len(building_names - failed_buildings)
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "road_count": len(ctx.drawing.roads),
            "building_count": len(ctx.drawing.buildings),
            "passed_buildings": passed_buildings,
            "failed_buildings": len(failed_buildings),
            "timing": {
                "t_convert": ctx.timing.t_convert,
                "t_parse": ctx.timing.t_parse,
                "t_review": ctx.timing.t_review,
                "t_render": ctx.timing.t_render,
                "t_total": ctx.timing.t_total,
            },
            "conversion_steps": ctx.conversion.steps if ctx.conversion else [],
            "dwg_mode": dwg_mode,
            "parse_mode": ctx.drawing.parse_mode,
            "confidence": ctx.drawing.confidence,
            "parse_warnings": ctx.drawing.parse_warnings,
            "report_url": artifact_url("html"),
            "image_url": artifact_url("image"),
            "timing_url": artifact_url("timing"),
            "artifact_groups": [],
        }
    )


@app.post("/api/analyze")
def analyze_upload():
    """上传 CAD 并返回原生图元/图层/语义对象汇总。"""

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return jsonify({"ok": False, "error": "请先选择 DXF 或 DWG 文件。"}), 400

    original_name = secure_filename(uploaded.filename) or "drawing.dxf"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        return jsonify({"ok": False, "error": "仅支持上传 .dxf 或 .dwg 文件。"}), 400

    dwg_mode = "strict"

    job_id = uuid4().hex[:12]
    job_upload_dir = UPLOAD_DIR / job_id
    job_output_dir = OUTPUT_DIR / job_id
    job_upload_dir.mkdir(parents=True, exist_ok=True)
    job_output_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_upload_dir / original_name
    uploaded.save(input_path)

    try:
        report = analyze_cad_file(input_path, job_output_dir, dwg_mode=dwg_mode)
        json_path = save_analysis_json(report, job_output_dir / f"{Path(original_name).stem}_analysis.json")
    except ValueError as exc:
        shutil.rmtree(job_output_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": str(exc)}), 422
    except Exception as exc:
        shutil.rmtree(job_output_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": f"分析失败：{exc}"}), 500

    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "report": report.to_dict(),
            "json_url": url_for("serve_artifact", job_id=job_id, filename=json_path.name),
        }
    )


@app.get("/artifacts/<job_id>/<path:filename>")
def serve_artifact(job_id: str, filename: str) -> Response:
    """提供 HTML 报告、PNG 标注图和 timing JSON 的静态访问。"""

    return send_from_directory(OUTPUT_DIR / job_id, filename)


def main() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
