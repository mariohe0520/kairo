"""
Kairo 配置管理 — 统一读取环境变量和 .env 文件。

所有外部 API Key 和运行时配置都从这里读取，
方便统一管理，也方便以后切换模型/提供商。
"""

import os
from pathlib import Path

# 自动加载同目录下的 .env 文件（如果存在）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # python-dotenv 未安装时手动解析
        with open(_env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = val

# ---------------------------------------------------------------------------
# AI 模型 API Keys（可选）
# ---------------------------------------------------------------------------

#: Claude API Key（高光 LLM 检测）
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

#: OpenAI API Key（备选 LLM）
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")

#: 火山引擎 ARK / 豆包 API Key（OpenAI 兼容格式）
ARK_API_KEY: str = os.environ.get("ARK_API_KEY", "")
ARK_BASE_URL: str = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
ARK_MODEL: str = os.environ.get("ARK_MODEL", "doubao-seed-2-0-pro-260215")

# ---------------------------------------------------------------------------
# 服务器配置
# ---------------------------------------------------------------------------

#: 监听端口（默认 8420）
KAIRO_PORT: int = int(os.environ.get("KAIRO_PORT", "8420"))

#: 监听 IP（默认 127.0.0.1 仅本机；0.0.0.0 允许局域网访问）
KAIRO_HOST: str = os.environ.get("KAIRO_HOST", "127.0.0.1")

# ---------------------------------------------------------------------------
# 视频处理配置
# ---------------------------------------------------------------------------

#: 单次上传最大文件大小（字节），默认 10GB
MAX_UPLOAD_SIZE_BYTES: int = int(
    os.environ.get("KAIRO_MAX_UPLOAD_GB", "10")
) * 1024 * 1024 * 1024

#: 同时运行的最大 pipeline 数（防止资源争抢）
MAX_CONCURRENT_PIPELINES: int = int(os.environ.get("KAIRO_MAX_PIPELINES", "2"))

#: 是否在 pipeline 完成后自动清理帧文件（默认开启，节省磁盘）
AUTO_CLEANUP_FRAMES: bool = os.environ.get("KAIRO_CLEANUP_FRAMES", "1") != "0"

#: Whisper ASR 模型（tiny/base/small/medium/large）
WHISPER_MODEL: str = os.environ.get("KAIRO_WHISPER_MODEL", "base")

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def has_llm() -> bool:
    """是否配置了任何 LLM API Key。"""
    return bool(ANTHROPIC_API_KEY or OPENAI_API_KEY or ARK_API_KEY)

def llm_provider() -> str:
    """返回当前使用的 LLM 提供商名称。"""
    if ANTHROPIC_API_KEY:
        return "claude"
    if OPENAI_API_KEY:
        return "openai"
    if ARK_API_KEY:
        return "ark"
    return "heuristic"

def print_config_summary() -> None:
    """启动时打印配置摘要（不打印 Key 本身）。"""
    import logging
    log = logging.getLogger("kairo.config")
    log.info("Kairo 配置：")
    log.info("  端口: %s:%d", KAIRO_HOST, KAIRO_PORT)
    log.info("  LLM: %s", llm_provider())
    log.info("  Whisper 模型: %s", WHISPER_MODEL)
    log.info("  最大并发 pipeline: %d", MAX_CONCURRENT_PIPELINES)
    log.info("  帧自动清理: %s", "开启" if AUTO_CLEANUP_FRAMES else "关闭")
    log.info("  最大上传: %d GB", MAX_UPLOAD_SIZE_BYTES // (1024**3))
