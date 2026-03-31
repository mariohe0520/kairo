"""
多模态分析层 — ASR + 视觉描述 + 时间轴对齐

按 +3 方案：两条独立管线（音频 ASR + 视频帧描述），最终以 time_sec 为主键对齐。
"""

import json
import subprocess
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import requests as _requests
except ImportError:
    _requests = None


@dataclass
class SecondAnnotation:
    time_sec: int
    time_str: str
    asr_text: str = ""
    frame_description: str = ""


@dataclass
class AnalyzeResult:
    timeline: list  # list of SecondAnnotation dicts
    total_seconds: int
    audio_path: str
    frames_dir: str


def analyze(
    video_path: str,
    work_dir: str,
    duration_sec: float,
    ollama_model: str = "qwen3.5:0.8b",
    ollama_url: str = "http://localhost:11434",
    max_workers: int = 4,
) -> AnalyzeResult:
    """执行完整的多模态分析"""
    audio_path = os.path.join(work_dir, "audio.wav")
    frames_dir = os.path.join(work_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    total_sec = int(duration_sec)

    # Step 1: 音频提取
    print("[分析] 提取音频...")
    _extract_audio(video_path, audio_path)

    # Step 2: 帧提取 (1 FPS, 640px)
    print("[分析] 提取视频帧 (1fps)...")
    _extract_frames(video_path, frames_dir)

    # Step 3: ASR 转录
    print("[分析] ASR 转录...")
    asr_by_sec = _run_asr(audio_path, total_sec)

    # Step 4: 视觉描述
    print("[分析] 视觉描述...")
    vision_by_sec = _run_vision(
        frames_dir, total_sec, ollama_model, ollama_url, max_workers
    )

    # Step 5: 时间轴对齐
    print("[分析] 合并时间轴...")
    timeline = []
    for sec in range(total_sec):
        ann = SecondAnnotation(
            time_sec=sec,
            time_str=f"{sec // 60:02d}:{sec % 60:02d}",
            asr_text=asr_by_sec.get(sec, ""),
            frame_description=vision_by_sec.get(sec, ""),
        )
        timeline.append(asdict(ann))

    # 保存 JSONL
    jsonl_path = os.path.join(work_dir, "timeline.jsonl")
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in timeline:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"[分析] 时间轴已保存: {jsonl_path} ({len(timeline)} 条)")

    return AnalyzeResult(
        timeline=timeline,
        total_seconds=total_sec,
        audio_path=audio_path,
        frames_dir=frames_dir,
    )


def _extract_audio(video_path: str, audio_path: str):
    """提取 16kHz 单声道 WAV"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ar", "16000",
        "-ac", "1",
        "-f", "wav",
        audio_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    print(f"[分析] 音频提取完成: {audio_path}")


def _extract_frames(video_path: str, frames_dir: str):
    """每秒 1 帧，缩放至 640px 宽"""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", "fps=1,scale=640:-1",
        "-q:v", "5",
        os.path.join(frames_dir, "frame_%04d.jpg"),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    frame_count = len(list(Path(frames_dir).glob("frame_*.jpg")))
    print(f"[分析] 帧提取完成: {frame_count} 帧")


def _run_asr(audio_path: str, total_sec: int) -> dict:
    """
    ASR 转录，按秒聚合。
    优先用 Whisper，fallback 到空结果（demo 仍可跑通）。
    """
    try:
        import whisper

        model = whisper.load_model("base")
        result = model.transcribe(audio_path, word_timestamps=True)

        by_sec = {}
        for seg in result.get("segments", []):
            for word_info in seg.get("words", []):
                sec = int(word_info["start"])
                if sec not in by_sec:
                    by_sec[sec] = []
                by_sec[sec].append(word_info["word"].strip())

        # 合并每秒的词为文本
        return {sec: " ".join(words) for sec, words in by_sec.items()}

    except ImportError:
        print("[分析] ⚠ Whisper 未安装，ASR 跳过 (pip install openai-whisper)")
        return {}
    except Exception as e:
        print(f"[分析] ⚠ ASR 失败: {e}")
        return {}


def _run_vision(
    frames_dir: str,
    total_sec: int,
    model: str,
    ollama_url: str,
    max_workers: int,
) -> dict:
    """
    用 Ollama VLM 描述每帧画面。
    按 +3 方案：4 线程并发，base64 编码图片输入。
    """
    if _requests is None:
        print("[分析] ⚠ requests 未安装，视觉描述跳过")
        return {}

    # 检查 Ollama 是否在线
    try:
        resp = _requests.get(f"{ollama_url}/api/tags", timeout=3)
        if resp.status_code != 200:
            raise ConnectionError()
    except Exception:
        print(f"[分析] ⚠ Ollama 不在线 ({ollama_url})，视觉描述跳过")
        return _vision_heuristic_fallback(frames_dir, total_sec)

    import base64

    results = {}
    frames = sorted(Path(frames_dir).glob("frame_*.jpg"))

    def describe_frame(idx_frame):
        idx, frame_path = idx_frame
        try:
            with open(frame_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Describe this video frame in under 50 words. Focus on: who is in frame, what they are doing, the setting, and any notable visual elements.",
                        "images": [img_b64],
                    }
                ],
                "stream": False,
                "options": {"num_predict": 100, "temperature": 0.3},
            }
            resp = _requests.post(
                f"{ollama_url}/api/chat", json=payload, timeout=30
            )
            if resp.status_code == 200:
                return idx, resp.json()["message"]["content"]
        except Exception as e:
            pass
        return idx, ""

    print(f"[分析] VLM 描述 {len(frames)} 帧 (并发={max_workers})...")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(describe_frame, (i, f)) for i, f in enumerate(frames)]
        done = 0
        for future in as_completed(futures):
            idx, desc = future.result()
            if desc:
                results[idx] = desc
            done += 1
            if done % 50 == 0:
                print(f"[分析] VLM 进度: {done}/{len(frames)}")

    return results


def _vision_heuristic_fallback(frames_dir: str, total_sec: int) -> dict:
    """无 VLM 时的兜底：基于帧文件大小粗估画面复杂度"""
    results = {}
    frames = sorted(Path(frames_dir).glob("frame_*.jpg"))
    if not frames:
        return results

    sizes = [f.stat().st_size for f in frames]
    avg_size = sum(sizes) / len(sizes) if sizes else 1

    for i, frame_path in enumerate(frames):
        size = frame_path.stat().st_size
        if size > avg_size * 1.3:
            results[i] = "complex scene with high visual activity"
        elif size < avg_size * 0.7:
            results[i] = "simple or static scene"
        else:
            results[i] = "moderate activity"

    print(f"[分析] 使用启发式兜底: {len(results)} 帧已标注")
    return results
