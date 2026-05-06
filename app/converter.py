from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConversionResult:
    """CAD 输入文件预处理结果。steps 用于在 Web/报告中展示转换过程。"""

    input_path: Path
    review_path: Path
    converted: bool = False
    t_convert: float = 0.0
    steps: list[str] = field(default_factory=list)


class ConversionError(RuntimeError):
    pass


def _find_oda_converter() -> Path | None:
    """查找 ODA File Converter。优先读取环境变量，随后检查 Windows 常见安装路径。"""

    env_path = os.getenv("ODA_FILE_CONVERTER") or os.getenv("ODA_CONVERTER")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    candidates = [
        Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"),
        Path(r"C:\Program Files\ODA\ODA File Converter\ODAFileConverter.exe"),
        Path(r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe"),
        Path(r"C:\Program Files (x86)\ODA\ODA File Converter\ODAFileConverter.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _latest_dxf(output_dir: Path) -> Path | None:
    files = sorted(output_dir.glob("*.dxf"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def prepare_cad_input(input_path: str | Path, work_dir: str | Path | None = None) -> ConversionResult:
    """准备审查输入文件。

    DXF 直接返回；DWG 则调用 ODA File Converter 自动转换为 DXF。转换过程会写入
    steps，供 Web 界面和日志用文字展示。ODA 命令行参数格式为：
    ODAFileConverter 输入目录 输出目录 输出版本 输出类型 递归 审计 输入过滤。
    """

    input_path = Path(input_path)
    suffix = input_path.suffix.lower()
    steps = [f"接收文件：{input_path.name}"]

    if suffix == ".dxf":
        steps.append("识别为 DXF 文件：无需格式转换，直接进入图纸解析。")
        return ConversionResult(input_path=input_path, review_path=input_path, converted=False, steps=steps)

    if suffix != ".dwg":
        raise ConversionError(f"不支持的 CAD 格式：{input_path.suffix}。请上传 DXF 或 DWG。")

    converter = _find_oda_converter()
    steps.append("识别为 DWG 文件：准备自动转换为 DXF。")
    if converter is None:
        steps.append("未检测到 ODA File Converter，无法自动转换 DWG。")
        raise ConversionError(
            "未检测到 ODA File Converter。请安装 ODA File Converter，或设置环境变量 "
            "ODA_FILE_CONVERTER 指向 ODAFileConverter.exe 后重试。"
        )

    work_dir = Path(work_dir) if work_dir else input_path.parent
    output_dir = work_dir / "converted_dxf"
    output_dir.mkdir(parents=True, exist_ok=True)
    steps.append(f"转换工具：{converter}")
    steps.append(f"转换输出目录：{output_dir}")

    started = time.perf_counter()
    command = [
        str(converter),
        str(input_path.parent),
        str(output_dir),
        "ACAD2018",
        "DXF",
        "0",
        "1",
        input_path.name,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    elapsed = time.perf_counter() - started
    steps.append(f"执行 DWG→DXF 转换，用时 {elapsed:.4f}s。")

    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        steps.append("转换失败：ODA File Converter 返回非零退出码。")
        raise ConversionError(f"DWG 自动转换失败：{stderr or '未知错误'}")

    converted_path = output_dir / f"{input_path.stem}.dxf"
    if not converted_path.exists():
        fallback = _latest_dxf(output_dir)
        if fallback is None:
            steps.append("转换失败：输出目录中未找到 DXF 文件。")
            raise ConversionError("DWG 自动转换失败：输出目录中未找到 DXF 文件。")
        converted_path = fallback

    steps.append(f"转换成功：{converted_path.name}")
    steps.append("进入 ParseAgent 图纸解析。")
    return ConversionResult(
        input_path=input_path,
        review_path=converted_path,
        converted=True,
        t_convert=elapsed,
        steps=steps,
    )
