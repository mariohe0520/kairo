#!/usr/bin/env python3
"""
Kairo AI Clip Editor — Integration Test Suite

Tests:
  1. Health endpoint
  2. Templates and personas listing
  3. Highlights detection (heuristic + LLM)
  4. Pipeline start with a short YouTube URL
  5. Job status polling
  6. Generic download endpoint

Usage:
    python3 test_pipeline.py
    python3 test_pipeline.py --url https://www.youtube.com/watch?v=<id>
    python3 test_pipeline.py --host 127.0.0.1 --port 8420
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# CLI args
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Kairo integration tests")
parser.add_argument("--host", default="127.0.0.1", help="Server host")
parser.add_argument("--port", default=8420, type=int, help="Server port")
parser.add_argument(
    "--url",
    default="https://www.youtube.com/watch?v=jNQXAC9IVRw",  # "Me at the zoo" — 18s, public domain
    help="Video URL to use for pipeline test",
)
parser.add_argument(
    "--skip-pipeline",
    action="store_true",
    help="Skip the full pipeline test (which downloads/transcribes video)",
)
args = parser.parse_args()

BASE = f"http://{args.host}:{args.port}"

# Local integration tests should bypass system HTTP proxies for localhost calls.
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"
INFO = "\033[36mINFO\033[0m"

results: list[tuple[str, bool, str]] = []


def _request(method: str, path: str, data: dict | None = None, form: dict | None = None) -> dict:
    """Simple HTTP request helper. Returns parsed JSON."""
    url = BASE + path
    body = None
    headers = {}

    if form is not None:
        encoded = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = encoded
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with LOCAL_OPENER.open(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {path}: {body_text[:400]}") from e


def record(name: str, ok: bool, note: str = "") -> None:
    results.append((name, ok, note))
    status = PASS if ok else FAIL
    print(f"  [{status}] {name}" + (f" — {note}" if note else ""))


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ---------------------------------------------------------------------------
# Test 1: Health check
# ---------------------------------------------------------------------------

section("1. Health Check")

try:
    health = _request("GET", "/api/health")
    ok = health.get("status") == "ok"
    record("health.status == ok", ok, f"got: {health.get('status')}")

    sys_info = health.get("system", {})
    record("health.system.ffmpeg", sys_info.get("ffmpeg") is True,
           f"ffmpeg={'yes' if sys_info.get('ffmpeg') else 'not found'}")
    record("health.system.yt_dlp", sys_info.get("yt_dlp") is True,
           f"yt-dlp={'yes' if sys_info.get('yt_dlp') else 'not found (URL downloads disabled)'}")
    record("health.system.whisper", sys_info.get("whisper") is True,
           f"whisper={'yes' if sys_info.get('whisper') else 'not found (transcription disabled)'}")
    record("health.system.llm", sys_info.get("llm") in ("claude", "openai", "heuristic"),
           f"llm={sys_info.get('llm', 'unknown')}")

    print(f"\n  {INFO} System: {json.dumps(sys_info, indent=4)}")

except Exception as e:
    record("health endpoint reachable", False, str(e))
    print(f"\n  Server not reachable at {BASE}. Is it running?")
    print("  Start with: ./start.sh")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Test 2: Templates
# ---------------------------------------------------------------------------

section("2. Templates Listing")

try:
    data = _request("GET", "/api/templates")
    templates = data.get("templates", [])
    record("templates list returned", isinstance(templates, list), f"{len(templates)} templates")
    record("templates has comeback-king", any(t["id"] == "comeback-king" for t in templates))
    record("templates has tiktok-vertical", any(t["id"] == "tiktok-vertical" for t in templates))

    # Test category filter
    fps_data = _request("GET", "/api/templates?category=FPS")
    fps_templates = fps_data.get("templates", [])
    record("category filter works", all(t["category"] == "FPS" for t in fps_templates),
           f"{len(fps_templates)} FPS templates")

except Exception as e:
    record("templates endpoint", False, str(e))

# ---------------------------------------------------------------------------
# Test 3: Personas
# ---------------------------------------------------------------------------

section("3. Personas Listing")

try:
    data = _request("GET", "/api/personas")
    personas = data.get("personas", [])
    record("personas list returned", isinstance(personas, list), f"{len(personas)} personas")
    record("personas has hype-streamer", any(p["id"] == "hype-streamer" for p in personas))
    record("personas has energy_level field", all("energy_level" in p for p in personas))
except Exception as e:
    record("personas endpoint", False, str(e))

# ---------------------------------------------------------------------------
# Test 4: Highlights detection
# ---------------------------------------------------------------------------

section("4. Highlights Detection (heuristic fallback)")

SAMPLE_TRANSCRIPT = json.dumps([
    {"start": 0.0, "end": 3.5, "text": "Oh my god, what was that!"},
    {"start": 3.5, "end": 7.0, "text": "Insane clutch, let's go!"},
    {"start": 7.0, "end": 12.0, "text": "I can't believe we won that round."},
    {"start": 12.0, "end": 18.0, "text": "Headshot, ace round, GG!"},
    {"start": 18.0, "end": 25.0, "text": "We're tilted but keep pushing."},
    {"start": 25.0, "end": 30.0, "text": "Rage quit incoming, no no no!"},
])

try:
    data = _request("POST", "/api/highlights", form={
        "transcript_json": SAMPLE_TRANSCRIPT,
        "template_id": "clutch-master",
        "max_highlights": 3,
    })
    highlights = data.get("highlights", [])
    llm = data.get("llm_used", "unknown")
    record("highlights returned", isinstance(highlights, list), f"{len(highlights)} highlights, llm={llm}")
    record("highlights not empty", len(highlights) > 0)
    if highlights:
        h = highlights[0]
        record("highlight has start/end", "start" in h and "end" in h,
               f"first: {h.get('start', '?')}s-{h.get('end', '?')}s")
        record("highlight has virality score", "virality" in h,
               f"virality={h.get('virality', '?')}")
except Exception as e:
    record("highlights endpoint", False, str(e))

# ---------------------------------------------------------------------------
# Test 5: Jobs list
# ---------------------------------------------------------------------------

section("5. Job Management")

try:
    data = _request("GET", "/api/jobs")
    jobs = data.get("jobs", [])
    record("jobs list returned", isinstance(jobs, list), f"{len(jobs)} existing jobs")
except Exception as e:
    record("jobs list endpoint", False, str(e))

# ---------------------------------------------------------------------------
# Test 6: Pipeline (optional — downloads a real video)
# ---------------------------------------------------------------------------

section("6. Full Pipeline Test")

if args.skip_pipeline:
    print(f"  [{SKIP}] Pipeline test skipped (--skip-pipeline flag)")
    results.append(("pipeline_test", True, "skipped"))
else:
    print(f"  {INFO} Starting pipeline with URL: {args.url}")
    print(f"  {INFO} This will download, transcribe, and render the video.")
    print(f"  {INFO} Use --skip-pipeline to skip this test.")
    print()

    try:
        # Start pipeline
        start_data = _request("POST", "/api/pipeline", form={
            "url": args.url,
            "template_id": "chill-highlights",
            "streamer_id": "test-user",
        })
        job_id = start_data.get("job_id")
        record("pipeline started", bool(job_id), f"job_id={job_id}")

        if job_id:
            # Poll until complete or failed (max 10 minutes)
            print(f"\n  {INFO} Polling job {job_id} ...")
            deadline = time.time() + 600
            last_msg = ""
            while time.time() < deadline:
                time.sleep(5)
                try:
                    job = _request("GET", f"/api/jobs/{job_id}")
                    status = job.get("status")
                    progress = round(job.get("progress", 0) * 100)
                    msg = job.get("message", "")
                    if msg != last_msg:
                        print(f"  [{INFO}] {status} {progress}% — {msg}")
                        last_msg = msg

                    if status == "completed":
                        result = job.get("result", {})
                        output = result.get("output_video") or result.get("output_path")
                        quality = result.get("quality_score", 0)
                        record("pipeline completed", True, f"quality={quality:.1f}/100")
                        record("pipeline has output video", bool(output), f"output={output}")

                        # Test download endpoint
                        if output:
                            download_url = f"{BASE}/api/jobs/{job_id}/download"
                            try:
                                req = urllib.request.Request(download_url, method="HEAD")
                                with LOCAL_OPENER.open(req, timeout=10) as resp:
                                    content_type = resp.headers.get("Content-Type", "")
                                    record(
                                        "download endpoint works",
                                        "video" in content_type,
                                        f"Content-Type: {content_type}",
                                    )
                            except Exception as dl_err:
                                record("download endpoint works", False, str(dl_err))
                        break

                    elif status == "failed":
                        error = job.get("error", "unknown")
                        record("pipeline completed", False, f"failed: {error[:200]}")
                        break

                except Exception as poll_err:
                    print(f"  [{FAIL}] Poll error: {poll_err}")
                    break
            else:
                record("pipeline completed within timeout", False, "timed out after 10 minutes")

    except Exception as e:
        record("pipeline start", False, str(e))

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

section("Results Summary")

total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed

for name, ok, note in results:
    status = PASS if ok else FAIL
    print(f"  [{status}] {name}" + (f" ({note})" if note else ""))

print(f"\n  Total: {total}  Passed: {passed}  Failed: {failed}")

if failed == 0:
    print(f"\n  \033[32mAll tests passed!\033[0m")
    sys.exit(0)
else:
    print(f"\n  \033[31m{failed} test(s) failed.\033[0m")
    sys.exit(1)
