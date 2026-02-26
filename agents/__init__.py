"""
Kairo Agents -- Intelligent core of the AI video editing pipeline.

Three agents work in sequence:

  1. **CaptionAgent**  (caption_agent.py)
     Multi-modal frame understanding.  Ingests sampled frames + ASR + audio
     energy and produces a richly annotated ``CaptionTimeline``.

  2. **DVDAgent**  (dvd_agent.py)
     Deep Video Discovery.  Scans the annotated timeline with sliding windows
     and triangulation scoring to surface the top viral clip candidates.

  3. **DNAAgent**  (dna_agent.py)
     Dynamic Narrative Architect.  Takes clip candidates and generates
     frame-accurate edit scripts with anti-fluff validation, voiceover
     scripts, and BGM sync directives.

Usage::

    from kairo.agents import CaptionAgent, DVDAgent, DNAAgent

    caption = CaptionAgent()
    timeline = caption.analyze(ingest_result)

    dvd = DVDAgent()
    candidates = dvd.discover(timeline)

    dna = DNAAgent()
    for candidate in candidates:
        script = dna.architect(candidate, timeline, template, persona)
"""

# --- Agents ---------------------------------------------------------------

from agents.caption_agent import CaptionAgent
from agents.dvd_agent import DVDAgent
from agents.dna_agent import DNAAgent

# --- Data types (CaptionAgent) --------------------------------------------

from agents.caption_agent import (
    CaptionTimeline,
    FrameAnalysis,
    GameSignal,
    EmotionSignal,
    AudienceSignal,
    SegmentAnnotation,
)

# --- Data types (DVDAgent) ------------------------------------------------

from agents.dvd_agent import (
    ClipCandidate,
    NarrativeArc,
    WindowScore,
)

# --- Data types (DNAAgent) ------------------------------------------------

from agents.dna_agent import (
    EditScript,
    EditBeat,
    BGMDirective,
)

__all__ = [
    # Agents
    "CaptionAgent",
    "DVDAgent",
    "DNAAgent",
    # CaptionAgent types
    "CaptionTimeline",
    "FrameAnalysis",
    "GameSignal",
    "EmotionSignal",
    "AudienceSignal",
    "SegmentAnnotation",
    # DVDAgent types
    "ClipCandidate",
    "NarrativeArc",
    "WindowScore",
    # DNAAgent types
    "EditScript",
    "EditBeat",
    "BGMDirective",
]
