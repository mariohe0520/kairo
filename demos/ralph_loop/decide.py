"""
内容决策层 — 关键词匹配 + 区间合并 + 片段定位

这是 +3 方案里最薄弱的部分。实现了他描述的算法：
1. 关键词匹配 → 标记候选秒
2. 连续秒合并为区间 (gap ≤ 3s 视为连续)
3. 过滤短区间 (< 5s)
4. 按"画面动态性 + 语音密度"加权排序
5. 选取 Top-N 片段
"""

from dataclasses import dataclass, field
from typing import Optional


# 内容类型关键词表
CONTENT_PROFILES = {
    "dance_party": {
        "keywords": [
            "dance", "dancing", "跳舞", "舞蹈", "party", "派对",
            "music", "dj", "beat", "groove", "move", "表演", "perform",
            "stage", "crowd", "audience", "观众", "欢呼", "cheer",
            "clap", "鼓掌", "applause", "energy", "hype",
        ],
        "template": "atmosphere",  # 氛围短视频 15-30s
        "target_duration": (15, 30),
        "keep_audio": False,  # BGM 驱动
    },
    "product_showcase": {
        "keywords": [
            "product", "商品", "展示", "价格", "buy", "购买",
            "quality", "品质", "recommend", "推荐", "link", "链接",
            "discount", "折扣", "sale", "offer",
        ],
        "template": "showcase",  # 种草视频 30-60s
        "target_duration": (30, 60),
        "keep_audio": True,  # 保留语音
    },
    "interview_dialogue": {
        "keywords": [
            "think", "认为", "opinion", "看法", "story", "故事",
            "experience", "经历", "why", "为什么", "how", "怎么",
            "feel", "感觉", "believe", "相信", "important", "重要",
        ],
        "template": "quote_clip",  # 金句切片 15-30s
        "target_duration": (15, 30),
        "keep_audio": True,  # 字幕驱动
    },
}

# 通用高能量关键词
HIGH_ENERGY_KEYWORDS = [
    "wow", "amazing", "incredible", "let's go", "oh my god", "omg",
    "winner", "champion", "victory", "celebration",
    "太棒了", "厉害", "冠军", "赢了", "加油", "精彩",
    "laugh", "笑", "cry", "哭", "scream", "尖叫",
    "fight", "打", "hit", "kick", "jump", "跳",
    "run", "跑", "fast", "quick", "rush",
]


@dataclass
class Segment:
    start_sec: int
    end_sec: int
    score: float
    content_type: str
    speech_density: float = 0.0
    visual_activity: float = 0.0

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


@dataclass
class DecideResult:
    segments: list  # list of Segment
    content_type: str
    template: str
    target_duration: tuple
    keep_audio: bool


def decide(timeline: list, top_n: int = 8) -> DecideResult:
    """
    执行内容决策：
    1. 判断内容类型
    2. 关键词评分每秒
    3. 合并连续区间
    4. 排序选取 Top-N
    """
    total_sec = len(timeline)
    if total_sec == 0:
        return DecideResult([], "dance_party", "atmosphere", (15, 30), False)

    # Step 1: 判断内容类型
    content_type = _detect_content_type(timeline)
    profile = CONTENT_PROFILES[content_type]
    print(f"[决策] 内容类型: {content_type} → 模板: {profile['template']}")

    # Step 2: 逐秒评分
    sec_scores = _score_seconds(timeline, content_type)

    # Step 3: 标记候选秒 (score > 0)
    candidate_secs = [sec for sec, score in sec_scores.items() if score > 0]
    candidate_secs.sort()

    if not candidate_secs:
        print("[决策] ⚠ 未找到高能量片段，使用均匀采样兜底")
        candidate_secs = list(range(0, total_sec, max(1, total_sec // (top_n * 2))))

    # Step 4: 合并连续秒为区间 (gap ≤ 3s)
    intervals = _merge_intervals(candidate_secs, max_gap=3)

    # Step 5: 过滤短区间 (< 5s)
    intervals = [(s, e) for s, e in intervals if e - s >= 5]

    if not intervals:
        print("[决策] ⚠ 过滤后无足够长的区间，降低阈值重试")
        intervals = _merge_intervals(candidate_secs, max_gap=5)
        intervals = [(s, e) for s, e in intervals if e - s >= 3]

    # Step 6: 为每个区间计算综合分
    segments = []
    for start, end in intervals:
        speech_density = _calc_speech_density(timeline, start, end)
        visual_activity = _calc_visual_activity(timeline, start, end)
        score_sum = sum(sec_scores.get(s, 0) for s in range(start, end))
        # 加权排序：画面动态性 0.6 + 语音密度 0.4
        composite = visual_activity * 0.6 + speech_density * 0.4 + score_sum * 0.01
        segments.append(Segment(
            start_sec=start,
            end_sec=end,
            score=composite,
            content_type=content_type,
            speech_density=speech_density,
            visual_activity=visual_activity,
        ))

    # Step 7: 排序选 Top-N，按时间顺序排列
    segments.sort(key=lambda s: s.score, reverse=True)
    selected = segments[:top_n]
    selected.sort(key=lambda s: s.start_sec)

    print(f"[决策] 选出 {len(selected)} 个片段:")
    for i, seg in enumerate(selected):
        print(
            f"  [{i+1}] {seg.start_sec}s-{seg.end_sec}s "
            f"({seg.duration}s) score={seg.score:.2f}"
        )

    return DecideResult(
        segments=selected,
        content_type=content_type,
        template=profile["template"],
        target_duration=profile["target_duration"],
        keep_audio=profile["keep_audio"],
    )


def _detect_content_type(timeline: list) -> str:
    """统计各类型关键词命中数，选最高的"""
    counts = {}
    all_text = " ".join(
        (e.get("asr_text", "") + " " + e.get("frame_description", "")).lower()
        for e in timeline
    )
    for ctype, profile in CONTENT_PROFILES.items():
        count = sum(1 for kw in profile["keywords"] if kw.lower() in all_text)
        counts[ctype] = count

    best = max(counts, key=counts.get)
    print(f"[决策] 类型检测: {counts} → {best}")
    return best


def _score_seconds(timeline: list, content_type: str) -> dict:
    """逐秒关键词评分"""
    profile_kws = CONTENT_PROFILES[content_type]["keywords"]
    all_kws = profile_kws + HIGH_ENERGY_KEYWORDS

    scores = {}
    for entry in timeline:
        sec = entry["time_sec"]
        text = (entry.get("asr_text", "") + " " + entry.get("frame_description", "")).lower()
        score = 0
        for kw in all_kws:
            if kw.lower() in text:
                score += 2 if kw in profile_kws else 1
        scores[sec] = score
    return scores


def _merge_intervals(secs: list, max_gap: int = 3) -> list:
    """将离散的秒合并为连续区间"""
    if not secs:
        return []
    intervals = []
    start = secs[0]
    prev = secs[0]
    for s in secs[1:]:
        if s - prev <= max_gap:
            prev = s
        else:
            intervals.append((start, prev + 1))
            start = s
            prev = s
    intervals.append((start, prev + 1))
    return intervals


def _calc_speech_density(timeline: list, start: int, end: int) -> float:
    """区间内有语音的秒数占比"""
    if end <= start:
        return 0.0
    speech_secs = sum(
        1 for entry in timeline[start:end]
        if entry.get("asr_text", "").strip()
    )
    return speech_secs / (end - start)


def _calc_visual_activity(timeline: list, start: int, end: int) -> float:
    """区间内画面动态性 (基于描述中的动态关键词)"""
    if end <= start:
        return 0.0
    dynamic_kws = [
        "dance", "jump", "run", "move", "walk", "fight", "perform",
        "跳", "跑", "走", "打", "动", "表演",
        "complex", "high visual activity", "crowd", "action",
    ]
    dynamic_secs = 0
    for entry in timeline[start:end]:
        desc = entry.get("frame_description", "").lower()
        if any(kw in desc for kw in dynamic_kws):
            dynamic_secs += 1
    return dynamic_secs / (end - start)
