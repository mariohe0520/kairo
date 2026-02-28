"""
Kairo Render Engine — FFmpeg-based intelligent video renderer.

Takes an EditScript (produced by the DNA agent) and renders the final output
video by cutting segments, applying effects and transitions, mixing audio
tracks, and burning subtitles.

Designed for macOS with VideoToolbox hardware acceleration support.
"""

import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("kairo.render")

WORKSPACE = Path(__file__).parent.parent
OUTPUT_DIR = WORKSPACE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class EditBeat:
    """A single beat in the edit timeline — one narrative unit."""

    phase: str  # hook, rising, climax, resolution, outro
    start: float  # source video timestamp (seconds)
    end: float  # source video timestamp (seconds)
    effects: list = field(default_factory=list)  # slowmo, zoom, shake, flash
    transition_in: str = "cut"  # cut, crossfade, whip, glitch
    transition_out: str = "cut"
    text_overlay: Optional[str] = None
    text_style: dict = field(default_factory=dict)
    pacing: float = 1.0  # playback speed (0.25 = quarter, 1 = normal, 2 = fast)
    music_cue: str = "sustain"  # build, drop, quiet, sustain

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def output_duration(self) -> float:
        """Actual duration after pacing adjustment."""
        if self.pacing <= 0:
            return self.duration
        return self.duration / self.pacing


@dataclass
class SubtitleSegment:
    """A single timed subtitle entry."""

    start: float
    end: float
    text: str
    style: dict = field(default_factory=dict)


@dataclass
class EditScript:
    """Complete edit plan produced by the DNA agent."""

    source_video: str
    beats: list  # list[EditBeat]
    bgm_config: dict = field(default_factory=lambda: {
        "path": None,
        "mood": "chill",
        "fade_in": 2.0,
        "fade_out": 3.0,
        "volume": 0.3,
    })
    subtitle_segments: list = field(default_factory=list)  # list[SubtitleSegment]
    voiceover_script: Optional[str] = None
    output_config: dict = field(default_factory=lambda: {
        "resolution": "1920x1080",
        "fps": 60,
        "codec": "libx264",
        "audio_codec": "aac",
        "format": "mp4",
        "crf": "18",
    })

    @property
    def total_source_duration(self) -> float:
        return sum(b.duration for b in self.beats)

    @property
    def total_output_duration(self) -> float:
        return sum(b.output_duration for b in self.beats)


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[str, float, str], None]
"""Signature: callback(stage: str, progress: float 0-1, message: str)"""


def _null_progress(stage: str, progress: float, message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Render Engine
# ---------------------------------------------------------------------------


class RenderEngine:
    """
    FFmpeg-based intelligent render engine for Kairo.

    Orchestrates the full render pipeline:
      1. Cut segments from source video at exact timestamps
      2. Apply per-beat effects (slow-mo, zoom, shake, flash, text overlays)
      3. Concatenate segments with transitions (crossfade, whip, glitch, cut)
      4. Mix audio layers (game audio, BGM, optional TTS voiceover)
      5. Burn subtitles (ASS format via drawtext or libass)

    Supports macOS VideoToolbox hardware acceleration.
    """

    def __init__(
        self,
        ffmpeg_bin: str = "ffmpeg",
        ffprobe_bin: str = "ffprobe",
        hwaccel: str = "auto",
        threads: int = 0,
        temp_dir: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ):
        self._ffmpeg = ffmpeg_bin
        self._ffprobe = ffprobe_bin
        self._hwaccel = hwaccel
        self._threads = threads
        self._temp_root = temp_dir or tempfile.mkdtemp(prefix="kairo_render_")
        self._progress = progress_callback or _null_progress
        self._run_id = f"render_{int(time.time())}_{os.getpid()}"

        # Detect VideoToolbox availability on macOS
        self._videotoolbox_available = self._detect_videotoolbox()
        # Detect drawtext filter (requires libfreetype, not always compiled in)
        self._drawtext_available = self._detect_drawtext()
        if not self._drawtext_available:
            logger.info("drawtext filter not available in this ffmpeg build — text overlays will be skipped")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(self, edit_script: EditScript, output_path: Optional[str] = None) -> str:
        """
        Render a complete video from an EditScript.

        Args:
            edit_script: The full edit plan with beats, audio config, subtitles.
            output_path: Optional explicit output path. Auto-generated if None.

        Returns:
            Absolute path to the rendered video file.
        """
        if not edit_script.beats:
            raise ValueError("EditScript contains no beats to render")

        source = edit_script.source_video
        if not os.path.isfile(source):
            raise FileNotFoundError(f"Source video not found: {source}")

        fmt = edit_script.output_config.get("format", "mp4")
        if output_path is None:
            output_path = str(OUTPUT_DIR / f"kairo_{self._run_id}.{fmt}")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        work_dir = os.path.join(self._temp_root, self._run_id)
        os.makedirs(work_dir, exist_ok=True)

        try:
            self._progress("init", 0.0, "Preparing render pipeline")
            logger.info("Render started: %d beats, source=%s", len(edit_script.beats), source)

            # Phase 1: Cut and process individual segments
            segment_paths = self._process_all_segments(
                source, edit_script.beats, edit_script.output_config, work_dir
            )

            # Phase 2: Concatenate with transitions
            self._progress("concat", 0.6, "Concatenating segments with transitions")
            transitions = self._extract_transitions(edit_script.beats)
            concat_path = os.path.join(work_dir, f"concat.{fmt}")
            self._concat_with_transitions(segment_paths, transitions, concat_path, edit_script)

            # Phase 3: Mix audio layers
            self._progress("audio", 0.75, "Mixing audio layers")
            audio_mixed_path = os.path.join(work_dir, f"audio_mixed.{fmt}")
            bgm_path = edit_script.bgm_config.get("path")
            vo_path = self._generate_voiceover(edit_script, work_dir) if edit_script.voiceover_script else None
            self._mix_audio(concat_path, bgm_path, vo_path, edit_script.bgm_config, audio_mixed_path)

            # Phase 4: Burn subtitles
            self._progress("subtitles", 0.9, "Burning subtitles")
            if edit_script.subtitle_segments:
                self._burn_subtitles(audio_mixed_path, edit_script.subtitle_segments, output_path)
            else:
                shutil.copy2(audio_mixed_path, output_path)

            self._progress("done", 1.0, f"Render complete: {output_path}")
            logger.info("Render complete: %s", output_path)
            return output_path

        finally:
            self._cleanup(work_dir)

    # ------------------------------------------------------------------
    # Phase 1: Segment cutting and per-beat effects
    # ------------------------------------------------------------------

    def _process_all_segments(
        self,
        source: str,
        beats: list,
        output_config: dict,
        work_dir: str,
    ) -> list:
        """Cut each beat from source and apply beat-level effects."""
        segment_paths = []
        total = len(beats)

        for idx, beat in enumerate(beats):
            progress = 0.05 + (idx / total) * 0.55
            self._progress(
                "segments",
                progress,
                f"Processing beat {idx + 1}/{total} ({beat.phase})",
            )

            fmt = output_config.get("format", "mp4")
            raw_path = os.path.join(work_dir, f"seg_{idx:04d}_raw.{fmt}")
            fx_path = os.path.join(work_dir, f"seg_{idx:04d}_fx.{fmt}")

            # Cut raw segment
            self._cut_segment(source, beat.start, beat.end, output_config, raw_path)

            # Apply effects (slow-mo, zoom, shake, flash, text overlay)
            # Only count text_overlay if drawtext is actually available
            needs_text = bool(beat.text_overlay) and self._drawtext_available
            if beat.effects or needs_text or beat.pacing != 1.0:
                self._apply_effects(raw_path, beat, output_config, fx_path)
                segment_paths.append(fx_path)
                _safe_remove(raw_path)
            else:
                segment_paths.append(raw_path)

        return segment_paths

    def _cut_segment(
        self,
        video_path: str,
        start: float,
        end: float,
        output_config: dict,
        output_path: str,
    ) -> str:
        """
        Cut a precise segment from the source video.

        Uses input seeking (-ss before -i) for speed, with -accurate_seek for
        frame-accurate cuts when durations are short.
        """
        duration = end - start
        if duration <= 0:
            raise ValueError(f"Invalid segment: start={start}, end={end}")

        codec = output_config.get("codec", "libx264")
        audio_codec = output_config.get("audio_codec", "aac")
        crf = output_config.get("crf", "18")

        cmd = [self._ffmpeg, "-y"]

        # Hardware acceleration (input side)
        cmd.extend(self._hwaccel_input_flags())

        # Input seeking — both -accurate_seek and -ss are INPUT options
        # and MUST appear before -i, not after it
        cmd.extend(["-accurate_seek"])
        cmd.extend(["-ss", f"{start:.6f}"])
        cmd.extend(["-i", video_path])
        cmd.extend(["-t", f"{duration:.6f}"])

        # Encoding
        cmd.extend(self._encoding_flags(codec, crf, audio_codec, output_config))
        cmd.extend(["-threads", str(self._threads)])
        cmd.extend(["-loglevel", "warning"])
        cmd.append(output_path)

        self._run_ffmpeg(cmd, f"cut_segment({start:.2f}-{end:.2f})")
        return output_path

    def _apply_effects(
        self,
        input_path: str,
        beat: "EditBeat",
        output_config: dict,
        output_path: str,
    ) -> str:
        """
        Apply beat-level effects to a segment.

        Supported effects:
          - slowmo: PTS manipulation via setpts filter
          - zoom: crop + scale for punch-in zoom
          - shake: random translate for camera shake
          - flash: white flash overlay via geq filter
          - text overlay: drawtext filter with styling
          - pacing: setpts + atempo for speed changes
        """
        video_filters = []
        audio_filters = []
        duration = beat.duration

        # --- Pacing / speed change ---
        if beat.pacing != 1.0:
            pts_factor = 1.0 / beat.pacing
            video_filters.append(f"setpts={pts_factor:.4f}*PTS")
            # Audio tempo adjustment (atempo only supports 0.5-2.0 range)
            audio_filters.extend(self._build_atempo_chain(beat.pacing))

        # --- Per-effect filters ---
        for effect in beat.effects:
            etype = effect if isinstance(effect, str) else effect.get("type", effect)
            params = effect if isinstance(effect, dict) else {}

            if etype == "slowmo":
                factor = params.get("factor", 0.5)
                if beat.pacing == 1.0:  # Avoid double-application if pacing already set
                    pts_factor = 1.0 / factor
                    video_filters.append(f"setpts={pts_factor:.4f}*PTS")
                    audio_filters.extend(self._build_atempo_chain(factor))

            elif etype == "zoom":
                zoom_factor = params.get("factor", 1.3)
                cx = params.get("center_x", 0.5)
                cy = params.get("center_y", 0.5)
                video_filters.append(self._build_zoom_filter(zoom_factor, cx, cy, output_config))

            elif etype == "shake":
                intensity = params.get("intensity", 0.5)
                video_filters.append(self._build_shake_filter(intensity, duration))

            elif etype == "flash":
                flash_duration = params.get("duration", 0.15)
                video_filters.append(
                    f"geq=lum='if(between(t,0,{flash_duration:.3f}),255,lum(X,Y))'"
                    f":cb='if(between(t,0,{flash_duration:.3f}),128,cb(X,Y))'"
                    f":cr='if(between(t,0,{flash_duration:.3f}),128,cr(X,Y))'"
                )

        # --- Text overlay (only if drawtext filter is available in this ffmpeg build) ---
        if beat.text_overlay and self._drawtext_available:
            video_filters.append(self._build_drawtext_filter(beat.text_overlay, beat.text_style))

        # Build command
        codec = output_config.get("codec", "libx264")
        audio_codec = output_config.get("audio_codec", "aac")
        crf = output_config.get("crf", "18")

        cmd = [self._ffmpeg, "-y"]
        cmd.extend(["-i", input_path])

        if video_filters:
            cmd.extend(["-vf", ",".join(video_filters)])
        if audio_filters:
            cmd.extend(["-af", ",".join(audio_filters)])

        cmd.extend(self._encoding_flags(codec, crf, audio_codec, output_config))
        cmd.extend(["-threads", str(self._threads)])
        cmd.extend(["-loglevel", "warning"])
        cmd.append(output_path)

        self._run_ffmpeg(cmd, f"apply_effects({beat.phase})")
        return output_path

    # ------------------------------------------------------------------
    # Phase 2: Concatenation with transitions
    # ------------------------------------------------------------------

    def _extract_transitions(self, beats: list) -> list:
        """
        Extract transition specifications between consecutive beats.
        Returns a list of dicts, one fewer than len(beats).
        """
        transitions = []
        for i in range(len(beats) - 1):
            current_out = beats[i].transition_out
            next_in = beats[i + 1].transition_in
            # Prefer the more complex transition
            chosen = self._pick_transition(current_out, next_in)
            transitions.append({
                "type": chosen,
                "duration": self._transition_duration(chosen),
            })
        return transitions

    def _concat_with_transitions(
        self,
        segment_paths: list,
        transitions: list,
        output_path: str,
        edit_script: "EditScript",
    ) -> str:
        """
        Concatenate segments with transitions.

        For simple cuts: uses concat demuxer (fast, stream-copy where possible).
        For crossfades: uses xfade video filter.
        For mixed: processes in stages.
        """
        if not segment_paths:
            raise ValueError("No segments to concatenate")

        if len(segment_paths) == 1:
            shutil.copy2(segment_paths[0], output_path)
            return output_path

        # Check if all transitions are hard cuts — use fast concat demuxer
        all_cuts = all(t["type"] == "cut" for t in transitions)
        if all_cuts:
            return self._concat_demuxer(segment_paths, output_path, edit_script)

        # Mixed transitions — build filter_complex with xfade
        return self._concat_xfade(segment_paths, transitions, output_path, edit_script)

    def _concat_demuxer(
        self,
        segment_paths: list,
        output_path: str,
        edit_script: "EditScript",
    ) -> str:
        """Fast concat via demuxer (stream copy, no re-encode)."""
        concat_list = os.path.join(os.path.dirname(output_path), "concat_list.txt")
        with open(concat_list, "w") as f:
            for p in segment_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd = [
            self._ffmpeg, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            "-loglevel", "warning",
            output_path,
        ]

        self._run_ffmpeg(cmd, "concat_demuxer")
        _safe_remove(concat_list)
        return output_path

    def _concat_xfade(
        self,
        segment_paths: list,
        transitions: list,
        output_path: str,
        edit_script: "EditScript",
    ) -> str:
        """
        Concatenate with xfade transitions.

        FFmpeg xfade filter chain for N inputs:
          [0][1]xfade=transition=T:duration=D:offset=O[v01];
          [v01][2]xfade=transition=T:duration=D:offset=O[v012]; ...

        Audio uses acrossfade for crossfades, or concat for cuts.
        """
        n = len(segment_paths)

        # Probe durations of all segments
        durations = [self._probe_duration(p) for p in segment_paths]

        cmd = [self._ffmpeg, "-y"]
        for p in segment_paths:
            cmd.extend(["-i", p])

        # Build xfade filter chain
        video_filters = []
        audio_filters = []
        running_offset = 0.0

        for i in range(n - 1):
            tr = transitions[i]
            tr_type = self._map_xfade_transition(tr["type"])
            tr_dur = min(tr["duration"], durations[i] * 0.5, durations[i + 1] * 0.5)
            tr_dur = max(tr_dur, 0.04)  # ffmpeg minimum

            # Video xfade offset is cumulative duration minus transition overlaps
            offset = running_offset + durations[i] - tr_dur
            if offset < 0:
                offset = 0.0

            if i == 0:
                vin_a = "[0:v]"
                ain_a = "[0:a]"
            else:
                vin_a = f"[vout{i - 1}]"
                ain_a = f"[aout{i - 1}]"

            vin_b = f"[{i + 1}:v]"
            ain_b = f"[{i + 1}:a]"

            vout = f"[vout{i}]" if i < n - 2 else "[vfinal]"
            aout = f"[aout{i}]" if i < n - 2 else "[afinal]"

            video_filters.append(
                f"{vin_a}{vin_b}xfade=transition={tr_type}:duration={tr_dur:.4f}:offset={offset:.4f}{vout}"
            )

            if tr_type in ("fade", "fadeblack", "fadewhite", "dissolve", "smoothleft", "smoothright"):
                audio_filters.append(
                    f"{ain_a}{ain_b}acrossfade=d={tr_dur:.4f}:c1=tri:c2=tri{aout}"
                )
            else:
                audio_filters.append(
                    f"{ain_a}{ain_b}concat=n=2:v=0:a=1{aout}"
                )

            running_offset = offset

        filter_complex = ";".join(video_filters + audio_filters)

        codec = edit_script.output_config.get("codec", "libx264")
        audio_codec = edit_script.output_config.get("audio_codec", "aac")
        crf = edit_script.output_config.get("crf", "18")

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[vfinal]", "-map", "[afinal]"])
        cmd.extend(self._encoding_flags(codec, crf, audio_codec, edit_script.output_config))
        cmd.extend(["-threads", str(self._threads)])
        cmd.extend(["-loglevel", "warning"])
        cmd.append(output_path)

        self._run_ffmpeg(cmd, "concat_xfade")
        return output_path

    # ------------------------------------------------------------------
    # Phase 3: Audio mixing
    # ------------------------------------------------------------------

    def _mix_audio(
        self,
        video_path: str,
        bgm_path: Optional[str],
        voiceover_path: Optional[str],
        bgm_config: dict,
        output_path: str,
    ) -> str:
        """
        Mix audio layers: game audio from video + BGM + optional voiceover.

        Game audio remains at full volume. BGM is ducked according to
        bgm_config.volume with fade in/out. Voiceover rides on top with
        slight game audio ducking.
        """
        if not bgm_path and not voiceover_path:
            # Nothing to mix — just copy
            shutil.copy2(video_path, output_path)
            return output_path

        video_duration = self._probe_duration(video_path)

        cmd = [self._ffmpeg, "-y"]
        cmd.extend(["-i", video_path])

        input_idx = 1
        bgm_idx = None
        vo_idx = None

        if bgm_path and os.path.isfile(bgm_path):
            cmd.extend(["-i", bgm_path])
            bgm_idx = input_idx
            input_idx += 1

        if voiceover_path and os.path.isfile(voiceover_path):
            cmd.extend(["-i", voiceover_path])
            vo_idx = input_idx
            input_idx += 1

        # Build audio filter graph
        filters = []
        mix_inputs = ["[0:a]"]

        if bgm_idx is not None:
            vol = bgm_config.get("volume", 0.3)
            fade_in = bgm_config.get("fade_in", 2.0)
            fade_out = bgm_config.get("fade_out", 3.0)

            bgm_filter = f"[{bgm_idx}:a]aloop=loop=-1:size=2e+09,atrim=0:{video_duration:.4f}"
            bgm_filter += f",volume={vol:.2f}"
            if fade_in > 0:
                bgm_filter += f",afade=t=in:st=0:d={fade_in:.2f}"
            if fade_out > 0:
                fade_start = max(0, video_duration - fade_out)
                bgm_filter += f",afade=t=out:st={fade_start:.2f}:d={fade_out:.2f}"
            bgm_filter += "[bgm]"
            filters.append(bgm_filter)
            mix_inputs.append("[bgm]")

        if vo_idx is not None:
            vo_filter = f"[{vo_idx}:a]volume=1.2[vo]"
            filters.append(vo_filter)
            mix_inputs.append("[vo]")

        n_inputs = len(mix_inputs)
        amix_inputs = "".join(mix_inputs)
        filters.append(
            f"{amix_inputs}amix=inputs={n_inputs}:duration=first:dropout_transition=2[amixed]"
        )

        filter_complex = ";".join(filters)

        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "0:v", "-map", "[amixed]"])
        cmd.extend(["-c:v", "copy"])
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd.extend(["-shortest"])
        cmd.extend(["-loglevel", "warning"])
        cmd.append(output_path)

        self._run_ffmpeg(cmd, "mix_audio")
        return output_path

    # ------------------------------------------------------------------
    # Phase 4: Subtitle burning
    # ------------------------------------------------------------------

    def _burn_subtitles(
        self,
        video_path: str,
        subtitle_segments: list,
        output_path: str,
    ) -> str:
        """
        Burn subtitles into the video using either ASS or drawtext filter.

        Generates a temporary ASS file and renders with libass via the
        'ass' video filter. Falls back to drawtext if libass is unavailable.
        """
        ass_path = os.path.join(os.path.dirname(output_path), "_kairo_subs.ass")
        self._generate_ass_file(subtitle_segments, ass_path)

        # Try libass first (better quality), fall back to subtitles filter
        cmd = [
            self._ffmpeg, "-y",
            "-i", video_path,
            "-vf", f"ass='{_escape_ffmpeg_path(ass_path)}'",
            "-c:a", "copy",
            "-loglevel", "warning",
            output_path,
        ]

        try:
            self._run_ffmpeg(cmd, "burn_subtitles_ass")
        except RuntimeError:
            logger.warning("libass failed, falling back to subtitles filter")
            cmd_fallback = [
                self._ffmpeg, "-y",
                "-i", video_path,
                "-vf", f"subtitles='{_escape_ffmpeg_path(ass_path)}'",
                "-c:a", "copy",
                "-loglevel", "warning",
                output_path,
            ]
            try:
                self._run_ffmpeg(cmd_fallback, "burn_subtitles_fallback")
            except RuntimeError:
                logger.warning("All subtitle filters unavailable — outputting without subtitles")
                shutil.copy2(video_path, output_path)

        _safe_remove(ass_path)
        return output_path

    def _generate_ass_file(self, subtitle_segments: list, output_path: str) -> None:
        """Generate an ASS subtitle file from SubtitleSegment list."""
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 1920\n"
            "PlayResY: 1080\n"
            "WrapStyle: 0\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: Default,Montserrat,58,&H00FFFFFF,&H000000FF,"
            "&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,30,30,60,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        lines = []
        for seg in subtitle_segments:
            s = seg if isinstance(seg, SubtitleSegment) else SubtitleSegment(**seg) if isinstance(seg, dict) else seg
            start_ts = _seconds_to_ass_time(s.start if hasattr(s, "start") else seg.get("start", 0))
            end_ts = _seconds_to_ass_time(s.end if hasattr(s, "end") else seg.get("end", 0))
            text = s.text if hasattr(s, "text") else seg.get("text", "")
            # Escape ASS special characters
            text = text.replace("\\", "\\\\").replace("\n", "\\N")

            # Apply style overrides from segment
            style_name = "Default"
            style_overrides = ""
            style_dict = s.style if hasattr(s, "style") else seg.get("style", {})
            if isinstance(style_dict, dict):
                if style_dict.get("bold"):
                    style_overrides += "\\b1"
                if style_dict.get("color"):
                    hex_color = style_dict["color"].lstrip("#")
                    if len(hex_color) == 6:
                        # ASS color format is &HBBGGRR& (BGR, reversed)
                        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
                        style_overrides += f"\\c&H{b}{g}{r}&"
                size = style_dict.get("size")
                if size:
                    size_map = {"small": 42, "medium": 58, "large": 72}
                    fs = size_map.get(size, 58) if isinstance(size, str) else int(size)
                    style_overrides += f"\\fs{fs}"

            if style_overrides:
                text = "{" + style_overrides + "}" + text

            lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},{style_name},,0,0,0,,{text}"
            )

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.writelines(line + "\n" for line in lines)

    # ------------------------------------------------------------------
    # Voiceover generation stub
    # ------------------------------------------------------------------

    def _generate_voiceover(self, edit_script: "EditScript", work_dir: str) -> Optional[str]:
        """
        Generate TTS voiceover from the voiceover_script field.

        Uses the Kokoro TTS model if available at the standard path.
        Returns path to generated audio, or None if generation fails.
        """
        script_text = edit_script.voiceover_script
        if not script_text:
            return None

        kokoro_bin = os.path.expanduser("~/.openclaw/models/kokoro-env/bin/kokoro")
        if not os.path.isfile(kokoro_bin):
            logger.warning("Kokoro TTS not found at %s, skipping voiceover", kokoro_bin)
            return None

        output_path = os.path.join(work_dir, "voiceover.wav")
        cmd = [
            "python3", "-m", "kokoro",
            "--text", script_text,
            "--output", output_path,
            "--voice", "af",
        ]

        try:
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=os.path.dirname(kokoro_bin),
            )
            if os.path.isfile(output_path):
                return output_path
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("Voiceover generation failed: %s", e)

        return None

    # ------------------------------------------------------------------
    # Filter builders
    # ------------------------------------------------------------------

    def _build_zoom_filter(
        self,
        factor: float,
        cx: float,
        cy: float,
        output_config: dict,
    ) -> str:
        """
        Build a crop+scale filter chain for zoom effect.

        Crops the frame to (1/factor) of its size centered at (cx, cy),
        then scales back up to the output resolution.
        """
        res = output_config.get("resolution", "1920x1080")
        out_w, out_h = (int(x) for x in res.split("x"))

        crop_w = int(out_w / factor)
        crop_h = int(out_h / factor)
        # Ensure even dimensions
        crop_w = crop_w - (crop_w % 2)
        crop_h = crop_h - (crop_h % 2)

        # Calculate crop offset so center maps to (cx, cy)
        x_offset = f"(iw-{crop_w})*{cx:.4f}"
        y_offset = f"(ih-{crop_h})*{cy:.4f}"

        return f"crop={crop_w}:{crop_h}:{x_offset}:{y_offset},scale={out_w}:{out_h}:flags=lanczos"

    def _build_shake_filter(self, intensity: float, duration: float) -> str:
        """
        Build a camera shake filter using random displacement.

        Uses the crop filter with time-varying offsets to simulate shake.
        """
        amplitude = max(2, int(intensity * 20))
        return (
            f"crop=iw-{amplitude * 2}:ih-{amplitude * 2}"
            f":x='{amplitude}+{amplitude}*sin(t*25)'"
            f":y='{amplitude}+{amplitude}*cos(t*30)'"
            f",scale=iw+{amplitude * 2}:ih+{amplitude * 2}:flags=fast_bilinear"
        )

    def _build_drawtext_filter(self, text: str, style: dict) -> str:
        """Build an ffmpeg drawtext filter for text overlay."""
        escaped_text = text.replace("'", "'\\''").replace(":", "\\:")
        font = style.get("font", "Montserrat")
        fontsize = style.get("size", 64)
        if isinstance(fontsize, str):
            fontsize = {"small": 42, "medium": 58, "large": 72}.get(fontsize, 58)
        color = style.get("color", "white")
        border_w = style.get("borderw", 3)
        position = style.get("position", "center")

        # Position mapping
        x_expr = "(w-text_w)/2"
        if position == "center":
            y_expr = "(h-text_h)/2"
        elif position == "top":
            y_expr = "h*0.1"
        else:  # bottom
            y_expr = "h*0.85"

        animation = style.get("animation", "none")
        alpha_expr = ""
        if animation == "fadeIn":
            alpha_expr = ":alpha='if(lt(t,0.5),t/0.5,1)'"
        elif animation == "slam":
            alpha_expr = ":alpha='if(lt(t,0.3),t/0.3,1)'"

        return (
            f"drawtext=text='{escaped_text}'"
            f":fontfile=/System/Library/Fonts/Helvetica.ttc"
            f":fontsize={fontsize}"
            f":fontcolor={color}"
            f":borderw={border_w}"
            f":bordercolor=black"
            f":x={x_expr}:y={y_expr}"
            f"{alpha_expr}"
        )

    def _build_atempo_chain(self, speed: float) -> list:
        """
        Build atempo filter chain for audio speed adjustment.

        atempo supports range [0.5, 100.0], so for very slow speeds
        we chain multiple atempo filters.
        """
        if speed <= 0:
            return []

        filters = []
        remaining = speed

        if remaining < 0.5:
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            if abs(remaining - 1.0) > 0.001:
                filters.append(f"atempo={remaining:.4f}")
        elif remaining > 100.0:
            while remaining > 100.0:
                filters.append("atempo=100.0")
                remaining /= 100.0
            if abs(remaining - 1.0) > 0.001:
                filters.append(f"atempo={remaining:.4f}")
        elif abs(remaining - 1.0) > 0.001:
            filters.append(f"atempo={remaining:.4f}")

        return filters

    # ------------------------------------------------------------------
    # Transition helpers
    # ------------------------------------------------------------------

    _TRANSITION_PRIORITY = {"cut": 0, "crossfade": 1, "whip": 2, "glitch": 3}

    def _pick_transition(self, a: str, b: str) -> str:
        """Pick the more complex of two transition types."""
        pa = self._TRANSITION_PRIORITY.get(a, 0)
        pb = self._TRANSITION_PRIORITY.get(b, 0)
        return a if pa >= pb else b

    @staticmethod
    def _transition_duration(tr_type: str) -> float:
        """Default duration for each transition type."""
        return {
            "cut": 0.0,
            "crossfade": 0.5,
            "whip": 0.3,
            "glitch": 0.25,
        }.get(tr_type, 0.0)

    @staticmethod
    def _map_xfade_transition(tr_type: str) -> str:
        """Map Kairo transition names to ffmpeg xfade transition names."""
        return {
            "cut": "fade",  # Minimal fade for cut (0-duration handled upstream)
            "crossfade": "fade",
            "whip": "smoothleft",
            "glitch": "pixelize",
        }.get(tr_type, "fade")

    # ------------------------------------------------------------------
    # Hardware acceleration
    # ------------------------------------------------------------------

    def _detect_drawtext(self) -> bool:
        """Check if ffmpeg has the drawtext filter compiled in (requires libfreetype)."""
        try:
            result = subprocess.run(
                [self._ffmpeg, "-filters"],
                capture_output=True, text=True, timeout=10,
            )
            return "drawtext" in (result.stdout + result.stderr)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _detect_videotoolbox(self) -> bool:
        """Check if VideoToolbox hardware acceleration is available."""
        if self._hwaccel == "none":
            return False
        try:
            result = subprocess.run(
                [self._ffmpeg, "-hide_banner", "-hwaccels"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # ffmpeg prints hwaccels to stdout; combine with stderr as a safety net
            combined = (result.stdout + result.stderr).lower()
            return "videotoolbox" in combined
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def _hwaccel_input_flags(self) -> list:
        """Return hwaccel flags for ffmpeg input, if applicable."""
        if self._hwaccel == "none":
            return []
        if self._hwaccel == "auto" and self._videotoolbox_available:
            return ["-hwaccel", "videotoolbox"]
        if self._hwaccel == "videotoolbox":
            return ["-hwaccel", "videotoolbox"]
        if self._hwaccel == "cuda":
            return ["-hwaccel", "cuda"]
        return []

    def _encoding_flags(
        self,
        codec: str,
        crf: str,
        audio_codec: str,
        output_config: dict,
    ) -> list:
        """Build encoding flags, selecting HW encoder when available."""
        flags = []

        # Try VideoToolbox encoder on macOS
        if self._videotoolbox_available and codec in ("libx264", "h264"):
            flags.extend(["-c:v", "h264_videotoolbox", "-q:v", "65"])
        elif self._videotoolbox_available and codec in ("libx265", "hevc"):
            flags.extend(["-c:v", "hevc_videotoolbox", "-q:v", "65"])
        else:
            flags.extend(["-c:v", codec, "-crf", crf])
            flags.extend(["-preset", "medium"])

        flags.extend(["-c:a", audio_codec])

        # Resolution and FPS
        res = output_config.get("resolution")
        if res and "x" in str(res):
            w, h = res.split("x")
            flags.extend(["-s", f"{w}x{h}"])

        fps = output_config.get("fps")
        if fps:
            flags.extend(["-r", str(fps)])

        # Pixel format for compatibility
        flags.extend(["-pix_fmt", "yuv420p"])

        return flags

    # ------------------------------------------------------------------
    # FFmpeg execution
    # ------------------------------------------------------------------

    def _run_ffmpeg(self, cmd: list, label: str, timeout: int = 600) -> subprocess.CompletedProcess:
        """Execute an ffmpeg command with error handling."""
        logger.debug("[%s] %s", label, " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"FFmpeg timed out after {timeout}s during '{label}'")
        except FileNotFoundError:
            raise RuntimeError(
                f"FFmpeg binary not found at '{self._ffmpeg}'. "
                "Install ffmpeg or set the ffmpeg_bin parameter."
            )

        if result.returncode != 0:
            stderr_tail = result.stderr[-2000:] if result.stderr else "(no stderr)"
            raise RuntimeError(
                f"FFmpeg failed during '{label}' (exit code {result.returncode}):\n{stderr_tail}"
            )

        return result

    def _probe_duration(self, video_path: str) -> float:
        """Get duration of a video file using ffprobe."""
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            video_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            info = json.loads(result.stdout)
            return float(info.get("format", {}).get("duration", 0))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            logger.warning("Could not probe duration for %s, defaulting to 0", video_path)
            return 0.0

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self, work_dir: str) -> None:
        """Remove temporary working directory."""
        try:
            if os.path.isdir(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
        except OSError:
            logger.warning("Failed to clean up work directory: %s", work_dir)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.CC)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ffmpeg_path(path: str) -> str:
    """Escape a file path for use inside ffmpeg filter strings."""
    return path.replace("\\", "/").replace("'", "'\\''").replace(":", "\\:")


def _safe_remove(path: str) -> None:
    """Remove a file if it exists, ignoring errors."""
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="[%(name)s] %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python render.py <source_video>")
        print("  Renders a demo edit script with two beats from the source video.")
        sys.exit(1)

    source = sys.argv[1]
    if not os.path.isfile(source):
        print(f"Error: file not found: {source}")
        sys.exit(1)

    # Build a simple demo EditScript
    demo_script = EditScript(
        source_video=source,
        beats=[
            EditBeat(
                phase="hook",
                start=0.0,
                end=5.0,
                effects=["zoom"],
                transition_out="crossfade",
                text_overlay="WATCH THIS",
                text_style={"size": 72, "position": "center", "animation": "slam"},
                pacing=1.0,
                music_cue="build",
            ),
            EditBeat(
                phase="climax",
                start=10.0,
                end=18.0,
                effects=[{"type": "slowmo", "factor": 0.5}],
                transition_in="crossfade",
                pacing=0.5,
                music_cue="drop",
            ),
            EditBeat(
                phase="outro",
                start=25.0,
                end=30.0,
                pacing=1.0,
                music_cue="quiet",
            ),
        ],
        subtitle_segments=[
            {"start": 0.0, "end": 5.0, "text": "The beginning of something epic", "style": {}},
            {"start": 5.0, "end": 18.0, "text": "CLUTCH MOMENT", "style": {"bold": True, "size": "large"}},
        ],
    )

    def on_progress(stage, pct, msg):
        print(f"  [{stage}] {pct * 100:.0f}% — {msg}")

    engine = RenderEngine(progress_callback=on_progress)
    out = engine.render(demo_script)
    print(f"\nDone! Output: {out}")
