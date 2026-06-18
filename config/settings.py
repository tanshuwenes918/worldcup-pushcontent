"""
配置管理模块 - 从 .env 文件加载所有配置项
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# 加载 .env
_env_path = Path(__file__).resolve().parent.parent / ".env"


def _load_env_fallback(path: Path) -> None:
    """Minimal .env loader used when python-dotenv is unavailable."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


if load_dotenv:
    load_dotenv(_env_path)
else:
    _load_env_fallback(_env_path)


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# ── 聚合数据 (原 API-Football) ──
JUHE_API_KEY: str = _get("JUHE_API_KEY") or _get("API_FOOTBALL_KEY")
API_FOOTBALL_KEY: str = JUHE_API_KEY  # 向后兼容

# ── LLM ──
LLM_BASE_URL: str = _get("LLM_BASE_URL")
LLM_API_KEY: str = _get("LLM_API_KEY")
LLM_MODEL: str = _get("LLM_MODEL", "gpt-4o")

# ── 飞书 ──
FEISHU_BASE_TOKEN: str = _get("FEISHU_BASE_TOKEN")
FEISHU_TABLE_ID: str = _get("FEISHU_TABLE_ID")
FEISHU_WEBHOOK_URL: str = _get("FEISHU_WEBHOOK_URL")
FEISHU_APP_ID: str = _get("FEISHU_APP_ID")
FEISHU_APP_SECRET: str = _get("FEISHU_APP_SECRET")

# ── lark-cli ──
LARK_CLI_PATH: str = _get("LARK_CLI_PATH", "")

# ── X (Twitter) Trending 爬取 ──
X_COOKIES: str = _get("X_COOKIES", "")
X_BASE_URL: str = _get("X_BASE_URL", "https://x.com")
X_EXPLORE_URL: str = _get("X_EXPLORE_URL", "https://x.com/explore/tabs/trending")
CLASH_PORT: str = _get("CLASH_PORT", "7892")

# ── 输出 ──
DRY_RUN: bool = _get("DRY_RUN", "false").lower() == "true"
OUTPUT_FORMAT: str = _get("OUTPUT_FORMAT", "both")
TIMEZONE: str = _get("TIMEZONE", "Asia/Shanghai")
MATCHDAY_MAX_MATCHES: int = int(_get("MATCHDAY_MAX_MATCHES", "12") or "12")
MATCHDAY_X_LIMIT: int = int(_get("MATCHDAY_X_LIMIT", "30") or "30")
MATCHDAY_MAX_PUSHES_PER_MATCH: int = int(_get("MATCHDAY_MAX_PUSHES_PER_MATCH", "2") or "2")

# ── 数据路径 ──
DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "outputs"

# 确保输出目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
