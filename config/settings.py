"""
配置管理模块 - 从 .env 文件加载所有配置项
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


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

# ── lark-cli ──
LARK_CLI_PATH: str = _get("LARK_CLI_PATH", r"C:\Users\AS\.workbuddy\binaries\node\versions\22.12.0\lark-cli.cmd")

# ── X (Twitter) Trending 爬取 ──
X_COOKIES: str = _get("X_COOKIES", "")
X_BASE_URL: str = _get("X_BASE_URL", "https://x.com")
X_EXPLORE_URL: str = _get("X_EXPLORE_URL", "https://x.com/explore/tabs/trending")
CLASH_PORT: str = _get("CLASH_PORT", "7892")

# ── 输出 ──
DRY_RUN: bool = _get("DRY_RUN", "false").lower() == "true"
OUTPUT_FORMAT: str = _get("OUTPUT_FORMAT", "both")
TIMEZONE: str = _get("TIMEZONE", "Asia/Shanghai")

# ── 数据路径 ──
DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "outputs"

# 确保输出目录存在
OUTPUT_DIR.mkdir(exist_ok=True)
