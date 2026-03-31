# Ralph Loop Demo

基于 +3 技术方案的端到端直播视频分析 → 竖屏短视频 pipeline demo。

## 架构

```
视频采集 (Playwright/yt-dlp)
    → 多模态分析 (ASR + VLM frame描述)
    → 内容决策 (关键词匹配 + 区间合并)
    → 视频生产 (竖屏快剪 + NumPy BGM + Pillow文字渲染)
```

## 安装

```bash
pip install -r requirements.txt
# 可选: playwright install chromium  (用于登录态采集)
# 必须: brew install ffmpeg
```

## 使用

```bash
# 用 yt-dlp 下载公开视频
python run.py --url "https://www.youtube.com/watch?v=XXXXX"

# 用本地视频文件
python run.py --input /path/to/video.mp4

# 用 Playwright 采集需要登录的平台
python run.py --url "https://some-platform.com/live/123" --playwright

# 指定输出
python run.py --input video.mp4 --output my_short.mp4 --title "DANCE CHALLENGE"
```

## 模块说明

| 文件 | 作用 |
|------|------|
| `run.py` | 入口，串联整个 pipeline |
| `acquire.py` | 视频采集 (Playwright + yt-dlp 双模式) |
| `analyze.py` | 多模态分析 (ASR + 视觉描述 + 时间轴对齐) |
| `decide.py` | 内容决策 (关键词评分 + 区间合并 + 片段定位) |
| `produce.py` | 视频生产 (竖屏裁切 + NumPy BGM + Pillow渲染 + 最终编码) |
