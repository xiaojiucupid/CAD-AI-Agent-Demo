from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConversionResult:
    """CAD 输入文件预处理结果。

    该对象由 `ConvertAgent` 生成，并传给后续 `ParseAgent`。它既保存真正要
    审查的 DXF 路径，也保存转换过程说明，便于报告和 Web 页面展示。
    """

    # input_path: 用户原始上传/输入的 CAD 文件路径，可能是 DXF 或 DWG。
    input_path: Path
    # review_path: 后续真正进入解析器的文件路径。DXF 输入时等于 input_path，DWG 输入时为转换后的 DXF。
    review_path: Path
    # converted: 是否发生了 DWG -> DXF 转换。
    converted: bool = False
    # t_convert: 转换耗时，单位秒。DXF 直接解析时为 0。
    t_convert: float = 0.0
    # steps: 转换过程文字日志，用于 Web 和 HTML 报告。
    steps: list[str] = field(default_factory=list)


class ConversionError(RuntimeError):
    """CAD 输入预处理失败时抛出的异常。"""

    pass


def _find_oda_converter() -> Path | None:
    """查找 ODA File Converter 可执行文件。

    查找顺序：
        1. 环境变量 `ODA_FILE_CONVERTER`。
        2. 环境变量 `ODA_CONVERTER`。
        3. Windows 常见安装路径。

    返回：
        找到时返回 exe 路径；找不到返回 None。
    """

    # env_path: 用户显式配置的 ODA 转换器路径，优先级最高。
    env_path = os.getenv("ODA_FILE_CONVERTER") or os.getenv("ODA_CONVERTER")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # candidates: Windows 上 ODA File Converter 常见安装路径。
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
    """返回输出目录中最新生成的 DXF 文件。

    ODA 转换后的文件名通常与 DWG stem 一致，但不同版本可能命名略有差异，
    因此保留该兜底逻辑。
    """

    # files: 按修改时间倒序排列的 DXF 文件列表。
    files = sorted(output_dir.glob("*.dxf"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None


def prepare_cad_input(input_path: str | Path, work_dir: str | Path | None = None) -> ConversionResult:
    """准备审查输入文件。

    参数：
        input_path: 用户传入的 CAD 文件路径。
        work_dir: 临时工作目录，Web 模式下通常是某个 job 输出目录。

    返回：
        `ConversionResult`，其中 `review_path` 一定指向后续可解析的 DXF。

    处理逻辑：
        - DXF：不转换，直接返回。
        - DWG：调用 ODA File Converter 转为 DXF。
        - 其他格式：抛出 `ConversionError`。
    """

    # input_path: 统一转为 Path，方便后续路径处理。
    input_path = Path(input_path)
    # suffix: 小写文件后缀，用于判断 CAD 格式。
    suffix = input_path.suffix.lower()
    # steps: 用户可读的处理过程日志。
    steps = [f"接收文件：{input_path.name}"]

    if suffix == ".dxf":
        steps.append("识别为 DXF 文件：无需格式转换，直接进入图纸解析。")
        return ConversionResult(input_path=input_path, review_path=input_path, converted=False, steps=steps)

    if suffix != ".dwg":
        raise ConversionError(f"不支持的 CAD 格式：{input_path.suffix}。请上传 DXF 或 DWG。")

    # converter: ODA File Converter 可执行文件路径。
    converter = _find_oda_converter()
    steps.append("识别为 DWG 文件：准备自动转换为 DXF。")
    if converter is None:
        steps.append("未检测到 ODA File Converter，无法自动转换 DWG。")
        raise ConversionError(
            "未检测到 ODA File Converter。请安装 ODA File Converter，或设置环境变量 "
            "ODA_FILE_CONVERTER 指向 ODAFileConverter.exe 后重试。"
        )

    # work_dir: 转换产物目录的父目录；缺省时使用输入文件所在目录。
    work_dir = Path(work_dir) if work_dir else input_path.parent
    # output_dir: ODA 转换输出 DXF 的目录。
    output_dir = work_dir / "converted_dxf"
    output_dir.mkdir(parents=True, exist_ok=True)
    steps.append(f"转换工具：{converter}")
    steps.append(f"转换输出目录：{output_dir}")

    # started: 转换开始时间，用于计算 t_convert。
    started = time.perf_counter()
    # command: ODA 命令行参数。含义依次为：输入目录、输出目录、输出版本、输出类型、递归、审计、输入过滤。
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
    # completed: ODA 子进程执行结果。
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    # elapsed: DWG 转 DXF 实际耗时。
    elapsed = time.perf_counter() - started
    steps.append(f"执行 DWG→DXF 转换，用时 {elapsed:.4f}s。")

    if completed.returncode != 0:
        # stderr: 转换失败时尽量提取 ODA 输出，方便用户定位环境问题。
        stderr = (completed.stderr or completed.stdout or "").strip()
        steps.append("转换失败：ODA File Converter 返回非零退出码。")
        raise ConversionError(f"DWG 自动转换失败：{stderr or '未知错误'}")

    # converted_path: 按约定推断出的转换后 DXF 文件路径。
    converted_path = output_dir / f"{input_path.stem}.dxf"
    if not converted_path.exists():
        # fallback: 若 ODA 输出文件名不符合预期，则取最新 DXF 作为兜底。
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
