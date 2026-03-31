#!/usr/bin/env python3
"""
Ralph Loop Demo — 端到端直播视频分析 → 竖屏短视频 pipeline

基于 +3 技术方案实现的完整 demo，串联四个阶段：
  采集 → 多模态分析 → 内容决策 → 视频生产

用法:
  python run.py --url "https://youtube.com/watch?v=..." [--output out.mp4]
  python run.py --input video.mp4 [--output out.mp4]
  python run.py --url "https://platform.com/live" --playwright
"""

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

# 把当前目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from acquire import acquire_with_ytdlp, acquire_with_playwright, use_local_file
from analyze import analyze
from decide import decide
from produce import produce


def main():
    parser = argparse.ArgumentParser(
        description="Ralph Loop: 直播视频分析 → 竖屏短视频"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="视频 URL (YouTube/Bilibili/直播平台)")
    group.add_argument("--input", help="本地视频文件路径")

    parser.add_argument("--output", default="ralph_output.mp4", help="输出路径")
    parser.add_argument("--playwright", action="store_true", help="使用 Playwright 采集 (需要登录的平台)")
    parser.add_argument("--auth-state", help="Playwright 登录态文件路径")
    parser.add_argument("--title", default="", help="视频主标题")
    parser.add_argument("--subtitle", default="", help="副标题")
    parser.add_argument("--watermark", default="@KAIRO", help="水印文字")
    parser.add_argument("--top-n", type=int, default=8, help="选取片段数")
    parser.add_argument("--ollama-model", default="qwen3.5:0.8b", help="Ollama VLM 模型")
    parser.add_argument("--work-dir", help="工作目录 (默认临时目录)")
    parser.add_argument("--keep-audio", action="store_true", help="保留原声 (混合BGM)")

    args = parser.parse_args()

    # 工作目录
    if args.work_dir:
        work_dir = args.work_dir
        os.makedirs(work_dir, exist_ok=True)
    else:
        work_dir = tempfile.mkdtemp(prefix="ralph_")

    print("=" * 60)
    print("  Ralph Loop — 直播视频智能分析与自动剪辑")
    print("=" * 60)
    print(f"  工作目录: {work_dir}")
    print()

    t0 = time.time()

    # ===== Stage 1: 采集 =====
    print("━" * 40)
    print("▶ Stage 1/4: 视频采集")
    print("━" * 40)
    t1 = time.time()

    if args.input:
        result = use_local_file(args.input)
    elif args.playwright:
        result = asyncio.run(
            acquire_with_playwright(args.url, work_dir, args.auth_state)
        )
    else:
        result = acquire_with_ytdlp(args.url, work_dir)

    title = args.title or result.title
    print(f"  ✓ 采集完成 ({time.time() - t1:.1f}s): {result.video_path}")
    print(f"  时长: {result.duration_sec:.0f}s, 标题: {title}")
    print()

    # ===== Stage 2: 多模态分析 =====
    print("━" * 40)
    print("▶ Stage 2/4: 多模态分析")
    print("━" * 40)
    t2 = time.time()

    analysis = analyze(
        result.video_path,
        work_dir,
        result.duration_sec,
        ollama_model=args.ollama_model,
    )

    asr_count = sum(1 for e in analysis.timeline if e.get("asr_text"))
    vis_count = sum(1 for e in analysis.timeline if e.get("frame_description"))
    print(f"  ✓ 分析完成 ({time.time() - t2:.1f}s)")
    print(f"  时间轴: {analysis.total_seconds}s, ASR 覆盖: {asr_count}s, 视觉描述: {vis_count}s")
    print()

    # ===== Stage 3: 内容决策 =====
    print("━" * 40)
    print("▶ Stage 3/4: 内容决策")
    print("━" * 40)
    t3 = time.time()

    decision = decide(analysis.timeline, top_n=args.top_n)

    total_clip_dur = sum(s.duration for s in decision.segments)
    print(f"  ✓ 决策完成 ({time.time() - t3:.1f}s)")
    print(f"  类型: {decision.content_type}, 模板: {decision.template}")
    print(f"  片段: {len(decision.segments)}个, 总时长: {total_clip_dur}s")
    print()

    # ===== Stage 4: 视频生产 =====
    print("━" * 40)
    print("▶ Stage 4/4: 视频生产")
    print("━" * 40)
    t4 = time.time()

    output_path = os.path.abspath(args.output)
    prod = produce(
        video_path=result.video_path,
        segments=decision.segments,
        work_dir=work_dir,
        output_path=output_path,
        title=title,
        subtitle_text=args.subtitle,
        watermark=args.watermark,
        keep_audio=args.keep_audio or decision.keep_audio,
    )

    print(f"  ✓ 生产完成 ({time.time() - t4:.1f}s)")
    print()

    # ===== 总结 =====
    total_time = time.time() - t0
    print("=" * 60)
    print("  Pipeline 完成!")
    print("=" * 60)
    print(f"  输入: {result.video_path} ({result.duration_sec:.0f}s)")
    print(f"  输出: {prod.output_path} ({prod.duration_sec:.1f}s)")
    print(f"  片段: {prod.segment_count}个")
    print(f"  总耗时: {total_time:.1f}s")
    print(f"  工作目录: {work_dir}")
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  输出文件: {file_size:.1f} MB")
    print()


if __name__ == "__main__":
    main()
