#!/usr/bin/env python3
"""
一键测试 — 零配置，自动生成测试视频并跑完整 pipeline
直接运行: python3 demos/ralph_loop/test_it.py
"""

import subprocess
import sys
import os
import tempfile
import shutil

DEMO_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DIR = os.path.join(tempfile.gettempdir(), "ralph_auto_test")


def step(msg):
    print(f"\n{'='*50}")
    print(f"  {msg}")
    print(f"{'='*50}\n")


def main():
    # 清理旧测试
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)
    os.makedirs(TEST_DIR)

    # Step 1: 检查依赖
    step("Step 1/3: 检查依赖")
    missing = []
    try:
        import numpy
        print(f"  numpy: {numpy.__version__} ✓")
    except ImportError:
        missing.append("numpy")

    try:
        from PIL import Image
        print(f"  Pillow: OK ✓")
    except ImportError:
        missing.append("Pillow")

    ffmpeg_ok = shutil.which("ffmpeg") is not None
    print(f"  ffmpeg: {'OK ✓' if ffmpeg_ok else 'NOT FOUND ✗'}")
    if not ffmpeg_ok:
        missing.append("ffmpeg (需要系统安装)")

    if missing:
        print(f"\n  缺少依赖: {', '.join(missing)}")
        print(f"  运行: pip install numpy Pillow")
        sys.exit(1)

    print("\n  所有必需依赖已就绪!")

    # Step 2: 生成测试视频 (30秒, 有画面变化 + 音频)
    step("Step 2/3: 自动生成 30 秒测试视频")
    test_video = os.path.join(TEST_DIR, "fake_live.mp4")
    cmd = [
        "ffmpeg", "-y",
        # 视频: 彩色条纹 + 计时器
        "-f", "lavfi", "-i",
        "testsrc2=duration=30:size=1920x1080:rate=30",
        # 音频: 变调正弦波模拟人声
        "-f", "lavfi", "-i",
        "sine=frequency=300:duration=30,tremolo=f=5:d=0.7",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k",
        "-shortest", test_video,
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)
    size_mb = os.path.getsize(test_video) / (1024 * 1024)
    print(f"  测试视频: {test_video}")
    print(f"  大小: {size_mb:.1f} MB")

    # Step 3: 跑 pipeline
    step("Step 3/3: 运行 Ralph Loop Pipeline")
    output = os.path.join(TEST_DIR, "output_short.mp4")
    run_script = os.path.join(DEMO_DIR, "run.py")

    result = subprocess.run(
        [
            sys.executable, run_script,
            "--input", test_video,
            "--output", output,
            "--title", "LIVE HIGHLIGHT",
            "--subtitle", "Auto Test Demo",
            "--watermark", "@KAIRO_TEST",
            "--work-dir", os.path.join(TEST_DIR, "work"),
        ],
        timeout=600,
    )

    # 结果
    print()
    if result.returncode == 0 and os.path.exists(output):
        out_mb = os.path.getsize(output) / (1024 * 1024)

        # 获取视频信息
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "stream=width,height,codec_name", "-of", "csv=p=0", output],
            capture_output=True, text=True, timeout=10,
        )
        info = probe.stdout.strip()

        print("=" * 50)
        print("  ✓ 测试通过!")
        print("=" * 50)
        print(f"  输出: {output}")
        print(f"  大小: {out_mb:.1f} MB")
        print(f"  格式: {info}")
        print()
        print("  你可以用任意视频播放器打开看效果:")
        print(f"  open {output}")
        print()
    else:
        print("=" * 50)
        print("  ✗ 测试失败!")
        print("=" * 50)
        print("  检查上面的错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
