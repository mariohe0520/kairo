"""
视频生产层 — 竖屏快剪 + NumPy BGM 合成 + Pillow 文字渲染

+3 方案的精华部分：
- 9:16 竖屏居中裁切
- 纯 NumPy Afrobeat 鼓点合成
- Pillow 逐帧渲染文字/遮罩绕过 drawtext 编译问题
"""

import os
import struct
import subprocess
import math
from pathlib import Path
from dataclasses import dataclass

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None


SAMPLE_RATE = 44100
BPM = 110
BEAT_SEC = 60.0 / BPM
SIXTEENTH = BEAT_SEC / 4


@dataclass
class ProduceResult:
    output_path: str
    duration_sec: float
    segment_count: int


def produce(
    video_path: str,
    segments: list,
    work_dir: str,
    output_path: str,
    title: str = "HIGHLIGHT REEL",
    subtitle_text: str = "",
    watermark: str = "@KAIRO",
    keep_audio: bool = False,
    fps: int = 20,
) -> ProduceResult:
    """完整的视频生产流程"""
    seg_dir = os.path.join(work_dir, "segments")
    os.makedirs(seg_dir, exist_ok=True)

    # Step 1: 切片 + 竖屏裁切
    print("[生产] 切割片段 + 竖屏适配...")
    seg_paths = []
    for i, seg in enumerate(segments):
        out = os.path.join(seg_dir, f"seg_{i:03d}.mp4")
        _cut_segment_vertical(video_path, seg.start_sec, seg.duration, out, keep_audio)
        if os.path.exists(out) and os.path.getsize(out) > 0:
            seg_paths.append(out)

    if not seg_paths:
        raise RuntimeError("所有片段切割失败")

    print(f"[生产] 切割完成: {len(seg_paths)} 个片段")

    # Step 2: 拼接片段
    concat_path = os.path.join(work_dir, "concat_raw.mp4")
    _concat_segments(seg_paths, concat_path)

    # Step 3: 合成 BGM
    total_dur = _get_duration(concat_path)
    bgm_path = os.path.join(work_dir, "bgm.wav")
    print("[生产] 合成 Afrobeat BGM...")
    _generate_afrobeat_bgm(bgm_path, total_dur)

    # Step 4: Pillow 文字渲染 (如果可用)
    if Image is not None:
        print("[生产] Pillow 渲染文字包装...")
        frames_dir = os.path.join(work_dir, "render_frames")
        os.makedirs(frames_dir, exist_ok=True)
        _render_text_overlay(concat_path, frames_dir, title, subtitle_text, watermark, fps)

        # 从渲染帧 + BGM 编码最终视频
        print("[生产] 最终编码...")
        _encode_final_from_frames(frames_dir, bgm_path, concat_path, output_path, fps, keep_audio)
    else:
        # 无 Pillow 兜底：直接混音
        print("[生产] ⚠ Pillow 不可用，跳过文字渲染，直接混音")
        _mix_audio_only(concat_path, bgm_path, output_path, keep_audio)

    final_dur = _get_duration(output_path)
    print(f"[生产] 完成: {output_path} ({final_dur:.1f}s)")
    return ProduceResult(
        output_path=output_path,
        duration_sec=final_dur,
        segment_count=len(seg_paths),
    )


# --------------- 竖屏切片 ---------------

def _cut_segment_vertical(video_path: str, start: float, duration: float, out_path: str, keep_audio: bool):
    """
    精准切片 + 9:16 竖屏裁切
    force_original_aspect_ratio=increase + crop=1080:1920 → 任意比例 → 竖屏居中
    """
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    cmd = [
        "ffmpeg", "-y",
        "-accurate_seek", "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
    ]
    if not keep_audio:
        cmd.append("-an")
    else:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
    cmd.append(out_path)
    subprocess.run(cmd, capture_output=True, timeout=60)


def _concat_segments(seg_paths: list, out_path: str):
    """拼接片段 (concat demuxer)"""
    list_path = out_path + ".txt"
    with open(list_path, "w") as f:
        for p in seg_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)


# --------------- NumPy BGM 合成 ---------------

def _generate_afrobeat_bgm(out_path: str, duration_sec: float):
    """
    纯 NumPy 合成 Afrobeat 风格鼓点。
    110 BPM, 4/4 拍。

    Kick:  X . . . | . . X . | X . . . | . . X .
    Snare: . . . . | X . . . | . . . . | X . . .
    HiHat: X . X . | X . X . | X . X . | X . X .
    Perc:  . . . X | . . . . | . X . . | . . . .
    Bass:  Amapiano-style log drum
    """
    n_samples = int(duration_sec * SAMPLE_RATE)
    mix = np.zeros(n_samples, dtype=np.float64)

    # 节拍时间网格
    total_16ths = int(duration_sec / SIXTEENTH)

    # Kick: 正弦波 + 指数衰减
    kick_pattern = [1, 0, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0]
    for i in range(total_16ths):
        if kick_pattern[i % 16]:
            mix = _add_kick(mix, int(i * SIXTEENTH * SAMPLE_RATE))

    # Snare: 噪声 + 衰减
    snare_pattern = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
    for i in range(total_16ths):
        if snare_pattern[i % 16]:
            mix = _add_snare(mix, int(i * SIXTEENTH * SAMPLE_RATE))

    # HiHat: 高频噪声
    hihat_pattern = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    for i in range(total_16ths):
        if hihat_pattern[i % 16]:
            mix = _add_hihat(mix, int(i * SIXTEENTH * SAMPLE_RATE))

    # Perc: 切分
    perc_pattern = [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
    for i in range(total_16ths):
        if perc_pattern[i % 16]:
            mix = _add_perc(mix, int(i * SIXTEENTH * SAMPLE_RATE))

    # Bass: Amapiano log drum (A-A-D-C | A-A-E-D)
    bass_notes = [220, 220, 293.66, 261.63, 220, 220, 329.63, 293.66]  # A3,A3,D4,C4,A3,A3,E4,D4
    beat_idx = 0
    for i in range(0, total_16ths, 2):  # 每 8 分音符一个 bass
        note = bass_notes[beat_idx % 8]
        mix = _add_bass(mix, int(i * SIXTEENTH * SAMPLE_RATE), note)
        beat_idx += 1

    # Fade in/out
    fade_samples = int(0.5 * SAMPLE_RATE)
    if n_samples > fade_samples * 2:
        fade_in = np.linspace(0, 1, fade_samples)
        fade_out = np.linspace(1, 0, fade_samples)
        mix[:fade_samples] *= fade_in
        mix[-fade_samples:] *= fade_out

    # Normalize
    peak = np.max(np.abs(mix))
    if peak > 0:
        mix = mix / peak * 0.8

    # Write WAV
    _write_wav(out_path, mix, SAMPLE_RATE)
    print(f"[生产] BGM 合成完成: {out_path} ({duration_sec:.1f}s)")


def _add_kick(mix, pos):
    dur = int(0.15 * SAMPLE_RATE)
    end = min(pos + dur, len(mix))
    t = np.arange(end - pos) / SAMPLE_RATE
    freq = 150 * np.exp(-t * 20)  # 下降扫频
    env = np.exp(-t * 15)
    signal = np.sin(2 * np.pi * freq * t) * env * 0.7
    mix[pos:end] += signal[:end - pos]
    return mix


def _add_snare(mix, pos):
    dur = int(0.1 * SAMPLE_RATE)
    end = min(pos + dur, len(mix))
    t = np.arange(end - pos) / SAMPLE_RATE
    noise = np.random.randn(end - pos) * 0.3
    tone = np.sin(2 * np.pi * 200 * t) * 0.2
    env = np.exp(-t * 20)
    mix[pos:end] += (noise + tone) * env
    return mix


def _add_hihat(mix, pos):
    dur = int(0.05 * SAMPLE_RATE)
    end = min(pos + dur, len(mix))
    t = np.arange(end - pos) / SAMPLE_RATE
    noise = np.random.randn(end - pos) * 0.15
    env = np.exp(-t * 40)
    mix[pos:end] += noise * env
    return mix


def _add_perc(mix, pos):
    dur = int(0.08 * SAMPLE_RATE)
    end = min(pos + dur, len(mix))
    t = np.arange(end - pos) / SAMPLE_RATE
    signal = np.sin(2 * np.pi * 800 * t) * np.exp(-t * 30) * 0.2
    mix[pos:end] += signal[:end - pos]
    return mix


def _add_bass(mix, pos, freq):
    dur = int(0.2 * SAMPLE_RATE)
    end = min(pos + dur, len(mix))
    t = np.arange(end - pos) / SAMPLE_RATE
    env = np.exp(-t * 8)
    signal = np.sin(2 * np.pi * freq * t) * env * 0.5
    mix[pos:end] += signal[:end - pos]
    return mix


def _write_wav(path: str, data: np.ndarray, sr: int):
    """写 16-bit mono WAV"""
    pcm = (data * 32767).astype(np.int16)
    with open(path, "wb") as f:
        # WAV header
        n_bytes = len(pcm) * 2
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + n_bytes))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", n_bytes))
        f.write(pcm.tobytes())


# --------------- Pillow 文字渲染 ---------------

def _render_text_overlay(
    video_path: str,
    frames_dir: str,
    title: str,
    subtitle: str,
    watermark: str,
    fps: int,
):
    """
    提取帧 → Pillow 绘制文字/遮罩 → 输出 PNG 序列

    视觉层次:
    - 顶部渐变遮罩 + LIVE 标识
    - 主标题 (白色, 大号) + 副标题 (橙色)
    - 底部渐变遮罩 + 水印
    """
    # 提取帧
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"fps={fps}",
        os.path.join(frames_dir, "%05d.png"),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)

    frames = sorted(Path(frames_dir).glob("*.png"))
    print(f"[生产] 提取 {len(frames)} 帧用于渲染")

    # 尝试加载字体
    font_title = _get_font(48)
    font_sub = _get_font(34)
    font_small = _get_font(22)
    font_caption = _get_font(28)

    for i, frame_path in enumerate(frames):
        img = Image.open(frame_path).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        w, h = img.size

        # 顶部渐变遮罩
        for y in range(min(120, h)):
            alpha = int(180 * (1 - y / 120))
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

        # 底部渐变遮罩
        for y in range(max(0, h - 150), h):
            alpha = int(180 * ((y - (h - 150)) / 150))
            draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

        # LIVE 标识 (左上)
        _draw_text_with_stroke(draw, (30, 20), "● LIVE", font_small, "red", "black", 2)

        # 主标题 (居中偏上)
        _draw_text_centered(draw, w, 60, title.upper(), font_title, "white", "black", 3)

        # 副标题
        if subtitle:
            _draw_text_centered(draw, w, 115, subtitle, font_sub, (255, 165, 0), "black", 2)

        # 字幕条 (底部)
        # 这里可以从 ASR 数据拿真实字幕，demo 暂用静态文本
        caption_y = h - 120
        caption_text = subtitle or title
        if caption_text:
            bbox = _get_text_bbox(draw, caption_text, font_caption)
            tw = bbox[2] - bbox[0]
            cx = (w - tw) // 2
            # 圆角半透明背景
            padding = 12
            draw.rounded_rectangle(
                [cx - padding, caption_y - padding, cx + tw + padding, caption_y + bbox[3] - bbox[1] + padding],
                radius=10,
                fill=(0, 0, 0, 160),
            )
            draw.text((cx, caption_y), caption_text, fill="white", font=font_caption)

        # 水印 (右下)
        _draw_text_with_stroke(
            draw, (w - 200, h - 40), watermark, font_small, (200, 200, 200), "black", 1
        )

        # 合成
        result = Image.alpha_composite(img, overlay).convert("RGB")
        result.save(frame_path)

        if (i + 1) % 100 == 0:
            print(f"[生产] 渲染进度: {i + 1}/{len(frames)}")

    print(f"[生产] 文字渲染完成: {len(frames)} 帧")


def _get_font(size: int):
    """尝试加载系统字体"""
    if ImageFont is None:
        return None
    # 常见字体路径
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw_text_with_stroke(draw, pos, text, font, fill, stroke_fill, stroke_width):
    """文字描边：8 方向绘制底层 + 顶层"""
    x, y = pos
    for dx in range(-stroke_width, stroke_width + 1):
        for dy in range(-stroke_width, stroke_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, fill=stroke_fill, font=font)
    draw.text(pos, text, fill=fill, font=font)


def _draw_text_centered(draw, width, y, text, font, fill, stroke_fill, stroke_width):
    """居中绘制带描边文字"""
    bbox = _get_text_bbox(draw, text, font)
    tw = bbox[2] - bbox[0]
    x = (width - tw) // 2
    _draw_text_with_stroke(draw, (x, y), text, font, fill, stroke_fill, stroke_width)


def _get_text_bbox(draw, text, font):
    try:
        return draw.textbbox((0, 0), text, font=font)
    except Exception:
        return (0, 0, len(text) * 10, 20)


# --------------- 最终编码 ---------------

def _encode_final_from_frames(
    frames_dir: str,
    bgm_path: str,
    source_video: str,
    output_path: str,
    fps: int,
    keep_audio: bool,
):
    """从渲染帧 + BGM (+ 可选原声) 编码最终 MP4"""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(frames_dir, "%05d.png"),
        "-i", bgm_path,
    ]

    if keep_audio:
        cmd.extend(["-i", source_video])
        # 混合原声和 BGM
        cmd.extend([
            "-filter_complex",
            "[1:a]volume=0.6[bgm];[2:a]volume=1.0[orig];[bgm][orig]amix=inputs=2:duration=shortest[aout]",
            "-map", "0:v",
            "-map", "[aout]",
        ])
    else:
        cmd.extend(["-map", "0:v", "-map", "1:a"])

    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ])
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


def _mix_audio_only(video_path: str, bgm_path: str, output_path: str, keep_audio: bool):
    """无 Pillow 时直接混音输出"""
    if keep_audio:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", bgm_path,
            "-filter_complex",
            "[1:a]volume=0.6[bgm];[0:a]volume=1.0[orig];[bgm][orig]amix=inputs=2:duration=shortest[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", bgm_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=300)


def _get_duration(video_path: str) -> float:
    import json as _json
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10)
        return float(_json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0
