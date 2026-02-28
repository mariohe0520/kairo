"""
Kairo Ingest Pipeline — Downloads, extracts, and preprocesses video content.
Handles: URL download, audio extraction, ASR transcription, frame sampling.
"""

import subprocess
import json
import os
import tempfile
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

WORKSPACE = Path(__file__).parent.parent
OUTPUT_DIR = WORKSPACE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class IngestResult:
    video_path: str
    audio_path: str
    transcript_path: str
    frames_dir: str
    duration_sec: float
    fps: float
    resolution: tuple
    transcript_segments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


def download_video(url: str, output_dir: str = None) -> str:
    """Download video from URL using yt-dlp. Supports Bilibili, YouTube, Twitch, etc."""
    if output_dir is None:
        output_dir = str(OUTPUT_DIR / "downloads")
    os.makedirs(output_dir, exist_ok=True)

    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    output_template = os.path.join(output_dir, f"kairo_{url_hash}_%(title)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--format", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--no-playlist",
        "--print", "after_move:filepath",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    filepath = result.stdout.strip().split("\n")[-1]
    if not os.path.exists(filepath):
        # Fallback: find the most recent file
        files = sorted(Path(output_dir).glob(f"kairo_{url_hash}_*"), key=os.path.getmtime)
        if files:
            filepath = str(files[-1])
        else:
            raise FileNotFoundError(f"Download succeeded but file not found")

    return filepath


def get_video_info(video_path: str) -> dict:
    """Get video metadata using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Install ffmpeg: brew install ffmpeg"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffprobe timed out for {video_path}")
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {video_path}: {result.stderr[:500]}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"ffprobe returned invalid JSON for {video_path}"
        )


def extract_audio(video_path: str, output_path: str = None) -> str:
    """Extract audio track as WAV for ASR processing."""
    if output_path is None:
        base = Path(video_path).stem
        output_path = str(OUTPUT_DIR / "audio" / f"{base}.wav")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        output_path
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return output_path


def transcribe_audio(audio_path: str, model: str = "base", language: str = None) -> dict:
    """Transcribe audio using Whisper with word-level timestamps."""
    cmd = [
        "whisper", audio_path,
        "--model", model,
        "--output_format", "json",
        "--word_timestamps", "True",
        "--output_dir", str(OUTPUT_DIR / "transcripts"),
    ]
    if language:
        cmd.extend(["--language", language])

    subprocess.run(cmd, capture_output=True, check=True, timeout=7200)

    json_path = str(OUTPUT_DIR / "transcripts" / f"{Path(audio_path).stem}.json")
    if os.path.exists(json_path):
        with open(json_path) as f:
            return json.load(f)
    return {"segments": [], "language": "unknown"}


def sample_frames(video_path: str, fps: float = 1.0, output_dir: str = None) -> str:
    """Extract frames at specified FPS for visual analysis."""
    if output_dir is None:
        base = Path(video_path).stem
        output_dir = str(OUTPUT_DIR / "frames" / base)
    os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",
        os.path.join(output_dir, "frame_%06d.jpg")
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=3600)
    return output_dir


def compute_audio_energy(audio_path: str, window_sec: float = 1.0) -> list:
    """Compute audio energy levels per second for emotion detection."""
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-af", f"astats=metadata=1:reset={int(1/window_sec)}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse RMS levels from ffmpeg output
    energy_levels = []
    for line in result.stderr.split("\n"):
        if "RMS level" in line:
            try:
                db = float(line.split(":")[-1].strip().split()[0])
                # Convert dB to 0-1 scale (roughly -60dB to 0dB range)
                normalized = max(0, min(1, (db + 60) / 60))
                energy_levels.append(normalized)
            except (ValueError, IndexError):
                pass

    return energy_levels


def ingest(source: str, language: str = None) -> IngestResult:
    """
    Full ingest pipeline: download/locate → extract audio → transcribe → sample frames.

    Args:
        source: URL or local file path
        language: Optional language hint for ASR
    Returns:
        IngestResult with all processed data paths
    """
    # Validate source
    if not source or not source.strip():
        raise ValueError("Source cannot be empty")

    # Step 1: Get or download video
    if source.startswith(("http://", "https://")):
        print(f"[Ingest] Downloading: {source}")
        video_path = download_video(source)
    else:
        video_path = source
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        # Validate file extension for local files
        valid_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"}
        ext = os.path.splitext(video_path)[1].lower()
        if ext not in valid_extensions:
            raise ValueError(
                f"Unsupported file format '{ext}'. "
                f"Supported: {', '.join(sorted(valid_extensions))}"
            )

    print(f"[Ingest] Video: {video_path}")

    # Step 2: Get video info
    info = get_video_info(video_path)
    if not info or not info.get("streams"):
        raise RuntimeError(
            f"ffprobe returned no stream data for {video_path}. "
            "File may be corrupted or not a valid video."
        )
    duration = float(info.get("format", {}).get("duration", 0))
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise RuntimeError(
            f"No video stream found in {video_path}. "
            "File may be audio-only or corrupted."
        )
    raw_fps = video_stream.get("r_frame_rate", "30/1")
    try:
        if "/" in str(raw_fps):
            num, den = str(raw_fps).split("/", 1)
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        else:
            fps = float(raw_fps)
    except (ValueError, ZeroDivisionError):
        fps = 30.0
    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))

    print(f"[Ingest] Duration: {duration:.0f}s, Resolution: {width}x{height}, FPS: {fps:.1f}")

    # Step 3: Extract audio
    print("[Ingest] Extracting audio...")
    audio_path = extract_audio(video_path)

    # Step 4: Transcribe
    print("[Ingest] Transcribing (this may take a while)...")
    whisper_model = "base" if duration < 3600 else "tiny"
    transcript = transcribe_audio(audio_path, model=whisper_model, language=language)

    transcript_path = str(OUTPUT_DIR / "transcripts" / f"{Path(video_path).stem}.json")

    # Step 5: Sample frames (1 fps for efficiency)
    print("[Ingest] Sampling frames...")
    sample_fps = 1.0 if duration < 7200 else 0.5
    frames_dir = sample_frames(video_path, fps=sample_fps)

    # Step 6: Compute audio energy
    print("[Ingest] Computing audio energy...")
    energy = compute_audio_energy(audio_path)

    return IngestResult(
        video_path=video_path,
        audio_path=audio_path,
        transcript_path=transcript_path,
        frames_dir=frames_dir,
        duration_sec=duration,
        fps=fps,
        resolution=(width, height),
        transcript_segments=transcript.get("segments", []),
        metadata={
            "language": transcript.get("language", "unknown"),
            "audio_energy": energy,
            "source": source,
        }
    )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ingest.py <url_or_path>")
        sys.exit(1)
    result = ingest(sys.argv[1])
    print(f"\n[Done] Video: {result.video_path}")
    print(f"[Done] Frames: {result.frames_dir}")
    print(f"[Done] Transcript: {result.transcript_path}")
    print(f"[Done] Duration: {result.duration_sec:.0f}s")
