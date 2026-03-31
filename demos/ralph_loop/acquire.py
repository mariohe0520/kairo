"""
视频采集层 — Playwright (登录态) + yt-dlp (公开) 双模式

+3 方案的核心亮点：Playwright 拦截网络请求捕获 HLS/DASH 流，
复用 storage_state 持久化登录态。
"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


@dataclass
class AcquireResult:
    video_path: str
    duration_sec: float
    title: str


def acquire_with_ytdlp(url: str, output_dir: str) -> AcquireResult:
    """用 yt-dlp 下载公开平台视频"""
    out_path = str(Path(output_dir) / "source.mp4")

    # 先获取标题
    title_cmd = ["yt-dlp", "--get-title", "--no-warnings", url]
    try:
        title = subprocess.check_output(title_cmd, text=True, timeout=30).strip()
    except Exception:
        title = "Untitled"

    # 下载视频
    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", out_path,
        "--no-warnings",
        url,
    ]
    print(f"[采集] yt-dlp 下载中: {url}")
    subprocess.run(cmd, check=True, timeout=600)

    duration = _get_duration(out_path)
    print(f"[采集] 完成: {out_path} ({duration:.0f}s)")
    return AcquireResult(video_path=out_path, duration_sec=duration, title=title)


async def acquire_with_playwright(
    url: str, output_dir: str, auth_state: Optional[str] = None
) -> AcquireResult:
    """
    用 Playwright 采集需要登录的平台视频。
    核心机制：浏览器渲染 → 网络请求监听 → 捕获 HLS/DASH URL → ffmpeg 下载
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "需要安装 playwright: pip install playwright && playwright install chromium"
        )

    captured_urls = []
    STREAM_SUFFIXES = (".m3u8", ".flv", ".mp4", ".ts")
    STREAM_CONTENT_TYPES = ("video/", "application/x-mpegurl", "application/dash+xml")

    def on_request(request):
        req_url = request.url.split("?")[0]
        if any(req_url.endswith(s) for s in STREAM_SUFFIXES):
            captured_urls.append(request.url)
            print(f"[采集] 捕获流 URL: {request.url[:100]}...")

    def on_response(response):
        ct = response.headers.get("content-type", "")
        if any(ct.startswith(t) for t in STREAM_CONTENT_TYPES):
            captured_urls.append(response.url)

    out_path = str(Path(output_dir) / "source.mp4")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 复用登录态
        context_kwargs = {}
        if auth_state and Path(auth_state).exists():
            context_kwargs["storage_state"] = auth_state
            print(f"[采集] 复用登录态: {auth_state}")

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        # 注册网络监听
        page.on("request", on_request)
        page.on("response", on_response)

        print(f"[采集] Playwright 加载页面: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 等待视频播放器加载并发起请求
        await asyncio.sleep(10)

        # 保存登录态供后续复用
        state_path = str(Path(output_dir) / "auth_state.json")
        await context.storage_state(path=state_path)
        print(f"[采集] 登录态已保存: {state_path}")

        await browser.close()

    if not captured_urls:
        raise RuntimeError("未捕获到流媒体 URL，可能需要手动登录一次")

    # 用 ffmpeg 下载捕获到的流
    stream_url = captured_urls[0]
    print(f"[采集] 用 ffmpeg 下载流: {stream_url[:100]}...")
    cmd = [
        "ffmpeg", "-y",
        "-i", stream_url,
        "-c", "copy",
        "-t", "1800",  # 最多30分钟
        out_path,
    ]
    subprocess.run(cmd, check=True, timeout=600)

    duration = _get_duration(out_path)
    title = Path(url).stem or "Live Stream"
    return AcquireResult(video_path=out_path, duration_sec=duration, title=title)


def use_local_file(path: str) -> AcquireResult:
    """直接使用本地视频文件"""
    if not Path(path).exists():
        raise FileNotFoundError(f"视频文件不存在: {path}")
    duration = _get_duration(path)
    title = Path(path).stem
    print(f"[采集] 使用本地文件: {path} ({duration:.0f}s)")
    return AcquireResult(video_path=path, duration_sec=duration, title=title)


def _get_duration(video_path: str) -> float:
    """用 ffprobe 获取视频时长"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    try:
        out = subprocess.check_output(cmd, text=True, timeout=10)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0
