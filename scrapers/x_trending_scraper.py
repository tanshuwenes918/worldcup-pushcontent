"""
X (Twitter) Trending 数据抓取器

独立的 Playwright 爬虫，专注 Sports 分类的世界杯相关内容。
完全不依赖 x-trending 项目。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── X 页面 URL ──
X_BASE_URL = os.getenv("X_BASE_URL", "https://x.com")
X_EXPLORE_URL = os.getenv("X_EXPLORE_URL", f"{X_BASE_URL}/explore/tabs/trending")

# ── 2026 世界杯 48 支参赛队伍 ──
# 基于 FIFA 官方参赛名单
WORLDCUP_2026_TEAMS = [
    # 东道主
    "united states", "usa", "canada", "mexico",
    # AFC (亚洲)
    "japan", "south korea", "korea republic", "saudi arabia", "australia",
    "iran", "iraq", "uzbekistan", "qatar", "united arab emirates", "uae",
    # CAF (非洲)
    "senegal", "morocco", "nigeria", "egypt", "cameroon", "ghana",
    "ivory coast", "cote d'ivoire", "algeria", "tunisia",
    # CONCACAF (中北美)
    "costa rica", "panama", "jamaica", "honduras",
    # CONMEBOL (南美)
    "argentina", "brazil", "uruguay", "colombia", "ecuador", "peru",
    "chile", "paraguay", "venezuela", "bolivia",
    # UEFA (欧洲)
    "france", "spain", "england", "germany", "portugal", "netherlands",
    "italy", "belgium", "croatia", "serbia", "switzerland", "denmark",
    "poland", "sweden", "turkey", "austria", "ukraine", "scotland",
    "wales", "norway", "czech republic", "hungary", "romania", "greece",
    # OFC (大洋洲)
    "new zealand",
]

# ── 世界杯关键词（中英文 + 球星名）──
WORLDCUP_KEYWORDS = [
    "world cup", "worldcup", "fifa", "世界杯", "cop28",
    "copa mundial", "copa do mundo", "piala dunia",
    "uefa", "champions league",
    # 球星名 (2026 活跃球员)
    "mbappe", "vinicius", "vinícius", "haaland", "messi", "ronaldo",
    "neymar", "bellingham", "kane", "salah", "de bruyne", "modric",
    "musiala", "pedri", "gavi", "lamin yamal", "yamal",
    "valverde", "rodrygo", "julian alvarez", "julián álvarez",
    "odegaard", "ødegaard", "saka", "foden", "palmer",
    "camavinga", "tchouameni", "gvardiol", "leao", "leão",
    "davies", "phil foden", "bruno fernandes", "osimhen",
    "kvara", "kvaratskhelia", "wirtz", "florian wirtz",
    # 传奇/退役球星 (可能被怀念/致敬)
    "pele", "pelé", "maradona", "zidane", "beckham", "ronaldinho",
]


def _get_proxy() -> Optional[Dict[str, str]]:
    """获取代理配置，优先读环境变量，回退到本地 Clash"""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy_url:
        return {"server": proxy_url}
    # 回退到本地 Clash 代理
    clash_port = os.environ.get("CLASH_PORT", "7892")
    return {"server": f"http://127.0.0.1:{clash_port}"}


def _get_cookies() -> List[Dict[str, Any]]:
    """从环境变量 X_COOKIES (HTTP Cookie header 格式) 解析 cookies"""
    raw = os.getenv("X_COOKIES", "")
    if not raw:
        return []
    cookies = []
    for item in raw.split(";"):
        item = item.strip()
        if "=" in item:
            name, _, value = item.partition("=")
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": ".x.com",
                "path": "/",
                "secure": True,
                "sameSite": "Lax",
            })
    return cookies


class XTrendingScraper:
    """X Sports 分类 Trending 抓取器（独立版本）"""

    # 输出缓存目录 (worldcup-pushcontent 自己的 outputs)
    OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"

    def __init__(self):
        self._playwright_available = self._check_playwright()

    def _check_playwright(self) -> bool:
        """检查 Playwright 是否可用"""
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            logger.warning("Playwright 未安装。请运行: pip install playwright && playwright install chromium")
            return False

    # ═══════════════════════════════════════════════════════════════
    # 公开方法
    # ═══════════════════════════════════════════════════════════════

    def get_sports_trending(self, query: str = "", limit: int = 20) -> Optional[dict]:
        """
        获取 X Sports 分类的世界杯相关内容

        Args:
            query: 可选搜索关键词（球员名/球队名），用于精确匹配
            limit: 最多返回的推文数

        Returns:
            {
                "topics": [...],      # 热门话题摘要
                "hashtags": [...],    # 热门标签
                "sentiments": [...],  # 情绪标注 (如可用)
                "raw_items": [...],   # 原始推文数据
                "scraped_at": "ISO timestamp",
            }
            如果爬取失败返回 None
        """
        # 1. 先检查缓存
        cached = self._load_cache()
        if cached and self._is_fresh(cached, max_age_minutes=30):
            filtered = self._filter_worldcup(cached, query)
            if filtered:
                logger.info("使用缓存 X Trending 数据 (age=%s)", cached.get("scraped_at", "unknown"))
                return filtered

        # 2. 实时爬取
        if self._playwright_available:
            try:
                return self._scrape_live(query, limit)
            except Exception as e:
                logger.warning("X 实时爬取失败: %s", e)

        # 3. 回退到缓存 (即使过期)
        if cached:
            logger.info("回退到过期缓存")
            return self._filter_worldcup(cached, query)

        return None

    def summarize_sentiment(self, trending_data: dict) -> str:
        """将 trending 数据总结为情绪摘要文本，供 LLM 输入使用"""
        topics = trending_data.get("topics", [])
        hashtags = trending_data.get("hashtags", [])
        sentiments = trending_data.get("sentiments", [])

        parts = []
        if topics:
            parts.append(f"热门话题: {', '.join(topics[:5])}")
        if hashtags:
            parts.append(f"热门标签: {', '.join(hashtags[:5])}")
        if sentiments:
            parts.append(f"情绪风向: {', '.join(sentiments[:3])}")

        return " | ".join(parts) if parts else "无 X Trending 数据"

    # ═══════════════════════════════════════════════════════════════
    # 实时爬取
    # ═══════════════════════════════════════════════════════════════

    def _scrape_live(self, query: str = "", limit: int = 20) -> Optional[dict]:
        """使用 Playwright 实时爬取 X Sports 分类"""
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

        print("  🌐 启动 Playwright 爬取 X Sports Trending...")
        with sync_playwright() as pw:
            proxy = _get_proxy()
            browser = pw.chromium.launch(
                headless=True,
                proxy=proxy,
            )
            context = browser.new_context(
                viewport={"width": 1400, "height": 1000},
                locale="en-US",
                timezone_id="Asia/Shanghai",
            )
            cookies = _get_cookies()
            if cookies:
                context.add_cookies(cookies)

            page = context.new_page()

            try:
                # 打开 X Trending 页面
                page.goto(X_EXPLORE_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)

                # 检查是否被重定向到登录页
                if "login" in page.url or "onboarding" in page.url:
                    logger.warning("X 需要登录。请设置 X_COOKIES 环境变量。")
                    browser.close()
                    return None

                # 点击 Sports 分类
                sports_clicked = self._click_category(page, "Sports")
                if not sports_clicked:
                    logger.warning("未找到 Sports 分类，尝试从当前页面提取数据")
                    # 即使没点到 Sports，也尝试提取当前可见的推文

                page.wait_for_timeout(2000)

                # 滚动收集推文
                tweets = self._collect_tweets(page, limit=limit * 3)

                browser.close()

                if not tweets:
                    return None

                # 转换为结构化数据
                result = {
                    "topics": [t.get("content", "")[:100] for t in tweets[:10]],
                    "hashtags": self._extract_hashtags(tweets),
                    "sentiments": [],  # X 不直接提供情绪
                    "raw_items": tweets[:limit],
                    "scraped_at": datetime.now(timezone.utc).isoformat(),
                }

                # 保存缓存
                self._save_cache(result)

                # 过滤世界杯相关内容
                return self._filter_worldcup(result, query)

            except PlaywrightTimeout:
                logger.warning("X 页面加载超时")
                browser.close()
                return None
            except Exception as e:
                logger.warning("Playwright 爬取出错: %s", e)
                browser.close()
                return None

    def _click_category(self, page, category: str) -> bool:
        """点击 X Trending 页面上的分类标签"""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        # 尝试多种匹配方式
        aliases = [category, category.lower(), category.upper()]
        for alias in aliases:
            try:
                # 先尝试精确文本匹配
                locator = page.get_by_text(alias, exact=True).first
                if locator.count() > 0:
                    locator.scroll_into_view_if_needed(timeout=5000)
                    locator.click(timeout=5000)
                    page.wait_for_timeout(2000)
                    return True
            except PlaywrightTimeout:
                pass
            except Exception:
                pass

        # 回退：尝试模糊匹配
        try:
            locator = page.get_by_text(category).first
            if locator.count() > 0:
                locator.click(timeout=5000)
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass

        return False

    def _collect_tweets(self, page, limit: int = 60) -> List[Dict[str, Any]]:
        """滚动页面收集推文"""
        tweets_by_url: Dict[str, Dict[str, Any]] = {}
        max_scrolls = 10

        for scroll_idx in range(max_scrolls):
            # 提取当前可见推文
            try:
                articles = page.locator('article[data-testid="tweet"]').all()
            except Exception:
                articles = []

            for article in articles:
                tweet = self._extract_tweet(article)
                url = tweet.get("tweet_url", "")
                if url and tweet.get("content"):
                    tweets_by_url[url] = tweet

            if len(tweets_by_url) >= limit:
                break

            # 滚动
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1500 if scroll_idx > 0 else 2500)

        return list(tweets_by_url.values())[:limit]

    def _extract_tweet(self, article) -> Dict[str, Any]:
        """从推文 article 元素提取结构化数据"""
        return {
            "author": self._extract_author(article),
            "content": self._extract_content(article),
            "created_at": self._extract_created_at(article),
            "likes": self._extract_metric(article, "like"),
            "retweets": self._extract_metric(article, "repost"),
            "replies": self._extract_metric(article, "reply"),
            "views": self._extract_metric(article, "view"),
            "tweet_url": self._extract_tweet_url(article),
        }

    def _extract_author(self, article) -> str:
        """提取推文作者 @handle"""
        try:
            name_locator = article.locator('[data-testid="User-Name"]').first
            if name_locator.count() == 0:
                return ""
            text = name_locator.inner_text(timeout=1000) or ""
            match = re.search(r"@[\w_]+", text)
            return match.group(0).lstrip("@") if match else text.split("\n")[0].strip()
        except Exception:
            return ""

    def _extract_content(self, article) -> str:
        """提取推文正文"""
        try:
            parts = []
            for node in article.locator('[data-testid="tweetText"]').all():
                text = node.inner_text(timeout=1000) or ""
                if text:
                    parts.append(text)
            return " ".join(" ".join(parts).split())
        except Exception:
            return ""

    def _extract_created_at(self, article) -> str:
        """提取推文发布时间"""
        try:
            time_locator = article.locator("time").first
            if time_locator.count() == 0:
                return ""
            return time_locator.get_attribute("datetime", timeout=1000) or ""
        except Exception:
            return ""

    def _extract_tweet_url(self, article) -> str:
        """提取推文 URL"""
        try:
            link = article.locator('a[href*="/status/"]').first
            if link.count() == 0:
                return ""
            href = link.get_attribute("href", timeout=1000) or ""
            if href and not href.startswith("http"):
                href = f"https://x.com{href}" if href.startswith("/") else f"https://x.com/{href}"
            return href
        except Exception:
            return ""

    def _extract_metric(self, article, metric: str) -> int:
        """提取推文互动指标 (like/repost/reply/view)"""
        selectors = {
            "like": ['[data-testid="like"]', '[data-testid="unlike"]', '[aria-label*="like" i]'],
            "repost": ['[data-testid="retweet"]', '[data-testid="unretweet"]',
                        '[aria-label*="repost" i]', '[aria-label*="retweet" i]'],
            "reply": ['[data-testid="reply"]', '[aria-label*="reply" i]'],
            "view": ['a[href$="/analytics"]', '[aria-label*="view" i]'],
        }

        for selector in selectors.get(metric, []):
            try:
                for locator in article.locator(selector).all():
                    aria = locator.get_attribute("aria-label", timeout=1000) or ""
                    if aria:
                        value = self._parse_metric_value(aria, metric)
                        if value:
                            return value
            except Exception:
                continue

        return 0

    def _parse_metric_value(self, text: str, metric: str) -> int:
        """从 aria-label 文本中解析数字"""
        keyword_map = {
            "like": r"likes?|liked",
            "repost": r"reposts?|retweets?",
            "reply": r"replies",
            "view": r"views?",
        }
        keyword = keyword_map.get(metric, "")
        pattern = rf"(\d+(?:[,.]\d+)?\s*[KkMmBb]?)\s*(?:{keyword})"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return self._compact_to_int(match.group(1))
        return 0

    def _compact_to_int(self, value: str) -> int:
        """Convert 1.2K / 3.4M / 5B to integer"""
        text = value.replace(",", "").replace(" ", "")
        multiplier = 1
        if text.upper().endswith("K"):
            multiplier = 1_000
            text = text[:-1]
        elif text.upper().endswith("M"):
            multiplier = 1_000_000
            text = text[:-1]
        elif text.upper().endswith("B"):
            multiplier = 1_000_000_000
            text = text[:-1]
        try:
            return int(float(text) * multiplier)
        except ValueError:
            return 0

    # ═══════════════════════════════════════════════════════════════
    # 缓存管理
    # ═══════════════════════════════════════════════════════════════

    def _cache_path(self) -> Path:
        """缓存文件路径"""
        self.OUTPUTS_DIR.mkdir(exist_ok=True)
        return self.OUTPUTS_DIR / "x_trending_cache.json"

    def _load_cache(self) -> Optional[dict]:
        """加载本地缓存"""
        cache_file = self._cache_path()
        if not cache_file.exists():
            return None
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_cache(self, data: dict) -> None:
        """保存数据到本地缓存"""
        try:
            self._cache_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.debug("缓存保存失败: %s", e)

    def _is_fresh(self, data: dict, max_age_minutes: int = 30) -> bool:
        """
        检查缓存数据是否足够新鲜

        FIXED: 没有时间戳 = 不可靠，返回 False (旧版错误地返回 True)
        """
        timestamp = data.get("scraped_at", "")
        if not timestamp:
            return False  # 没有时间戳 → 不信任，需要重新爬取
        try:
            # 处理各种 ISO 时间戳格式
            ts = timestamp.replace("Z", "+00:00")
            scraped_time = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            age_minutes = (now - scraped_time).total_seconds() / 60
            return 0 <= age_minutes <= max_age_minutes
        except Exception:
            return False  # 解析失败 → 不信任

    # ═══════════════════════════════════════════════════════════════
    # 内容过滤
    # ═══════════════════════════════════════════════════════════════

    def _filter_worldcup(self, data: dict, query: str = "") -> Optional[dict]:
        """从爬取数据中过滤世界杯相关内容"""
        raw_items = data.get("raw_items", [])
        if not raw_items:
            return None

        # 合并所有关键词
        all_keywords = list(WORLDCUP_KEYWORDS) + WORLDCUP_2026_TEAMS

        def is_relevant(item: dict) -> bool:
            text = json.dumps(item, ensure_ascii=False).lower()
            if query and query.lower() in text:
                return True
            return any(kw in text for kw in all_keywords)

        filtered = [item for item in raw_items if is_relevant(item)]

        if not filtered:
            return None

        return {
            "topics": [item.get("content", "")[:100] for item in filtered[:10]],
            "hashtags": self._extract_hashtags(filtered),
            "sentiments": data.get("sentiments", []),
            "raw_items": filtered[:20],
            "scraped_at": data.get("scraped_at", ""),
        }

    def _extract_hashtags(self, items: list) -> list:
        """
        从推文内容中提取 hashtag

        FIXED: regex matches non-whitespace non-# after #, supports non-ASCII tags
        """
        hashtags = set()
        for item in items:
            content = item.get("content", "") or item.get("summary", "")
            # 匹配 # 后跟非空白非 # 字符
            found = re.findall(r"#([^\s#]+)", content)
            hashtags.update(tag.rstrip(".,;:!?）)】」\"'") for tag in found)
        # 按字母序排列，去重后取前 15 个
        return sorted(hashtags, key=str.lower)[:15]
