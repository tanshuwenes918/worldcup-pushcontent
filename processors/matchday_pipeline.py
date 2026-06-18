"""
比赛日自动化管线。

GitHub Actions 定时触发时使用：
1. 聚合数据 API 拉取官方赛程
2. Playwright 抓取 X Sports Trending 并过滤世界杯相关内容
3. 合并两路数据后送入 LLM 生成 7 语言 Push
4. 写入飞书多维表格，并保存 JSON 归档
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import settings
from data_sources.api_football import APIFootballClient
from exporters.bitable_exporter import BitableExporter
from processors.matchday_generator import MatchdayPushGenerator
from scrapers.x_trending_scraper import XTrendingScraper


def build_sample_matches() -> list[dict]:
    """本地验证用样例，不访问外部 API。"""
    return [
        {
            "fixture_id": "sample-fra-bra",
            "date": datetime.now().isoformat(),
            "venue": "MetLife Stadium",
            "stage": "小组赛",
            "group": "G组",
            "team_home": {"name": "法国", "code": "FRA", "score": None},
            "team_away": {"name": "巴西", "code": "BRA", "score": None},
            "status": "NS",
            "match_des": "未开赛",
        }
    ]


def build_sample_trending() -> dict:
    """本地验证用 X 热点样例，不包含真实 cookie 或真实推文。"""
    return {
        "topics": [
            "Fans are already arguing about France vs Brazil and who owns the wings.",
            "World Cup watch parties are forming around Brazil dance edits.",
        ],
        "hashtags": ["WorldCup2026", "FRA", "BRA", "Vini", "Mbappe"],
        "sentiments": ["hype", "banter", "watch-party"],
        "raw_items": [
            {
                "author": "sample",
                "content": "France vs Brazil has everyone picking sides before kickoff #WorldCup2026",
                "likes": 1200,
                "retweets": 210,
                "views": 45000,
                "tweet_url": "",
            }
        ],
        "scraped_at": datetime.now().isoformat(),
    }


class MatchdayPipeline:
    """比赛日端到端流程。"""

    def __init__(
        self,
        match_date: str = "",
        limit: int | None = None,
        dry_run: bool = False,
        skip_x: bool = False,
        mock_llm: bool = False,
        sample_data: bool = False,
    ):
        self.match_date = match_date
        self.limit = limit or settings.MATCHDAY_MAX_MATCHES
        self.dry_run = dry_run
        self.skip_x = skip_x
        self.mock_llm = mock_llm
        self.sample_data = sample_data

    def run(self) -> dict:
        print("\n============================================================")
        print("  Vanso Matchday Push Pipeline")
        print(f"  Date: {self.match_date or 'today'} | Limit: {self.limit}")
        print("============================================================\n")

        matches = self._load_matches()
        if self.limit:
            matches = matches[: self.limit]
        if not matches:
            result = {
                "pipeline": "matchday",
                "match_date": self.match_date or "today",
                "generated_at": datetime.now().isoformat(),
                "source_data": {"matches_count": 0, "x_trending_count": 0, "x_hashtags": []},
                "items": [],
                "exported_record_ids": [],
            }
            output_path = self._save_result(result)
            print(f"[4/5] JSON 已保存: {output_path}")
            print("[5/5] 完成: 0 场比赛，写入 0 条记录\n")
            return result

        trending = self._load_trending(matches)
        opportunities = self._build_opportunities(matches, trending)
        generator = MatchdayPushGenerator(mock=self.mock_llm)

        content_entries = []
        for idx, opportunity in enumerate(opportunities, start=1):
            match = opportunity["match"]
            display = self._match_display(match)
            print(f"[3/5] 生成 {idx}/{len(opportunities)}: {display} | {opportunity['title']}")
            content = generator.generate(match, trending, opportunity)
            content_entries.append({
                "match": match,
                "trigger": opportunity,
                "content": content,
                "result": self._to_export_result(match, content, trending, opportunity),
            })

        result = {
            "pipeline": "matchday",
            "match_date": self.match_date or "today",
            "generated_at": datetime.now().isoformat(),
            "source_data": {
                "matches_count": len(matches),
                "opportunities_count": len(opportunities),
                "x_trending_count": len((trending or {}).get("raw_items", [])),
                "x_hashtags": (trending or {}).get("hashtags", []),
            },
            "items": content_entries,
        }

        output_path = self._save_result(result)
        print(f"[4/5] JSON 已保存: {output_path}")

        exported = self._export(content_entries)
        result["exported_record_ids"] = exported
        print(f"[5/5] 完成: {len(matches)} 场比赛，{len(content_entries)} 个触发机会，写入 {len(exported)} 条记录\n")
        return result

    def _load_matches(self) -> list[dict]:
        print("[1/5] 拉取聚合数据赛程...")
        if self.sample_data:
            matches = build_sample_matches()
        else:
            matches = APIFootballClient().get_matchday_matches(self.match_date)

        if not matches:
            print("  ! 比赛日没有赛程，结束。")
            return []

        print(f"  OK 获取到 {len(matches)} 场比赛")
        return matches

    def _load_trending(self, matches: list[dict]) -> dict:
        print("[2/5] 获取 X Sports Trending...")
        if self.sample_data:
            trending = build_sample_trending()
        elif self.skip_x:
            trending = {}
            print("  ! 已跳过 X Trending")
        else:
            query = " ".join(self._team_tokens(matches))
            trending = XTrendingScraper().get_sports_trending(query=query, limit=settings.MATCHDAY_X_LIMIT) or {}

        if trending:
            print(
                f"  OK X 相关内容 {len(trending.get('raw_items', []))} 条，"
                f"hashtags {len(trending.get('hashtags', []))} 个"
            )
        else:
            print("  ! 没有可用 X Trending 数据，将仅使用官方赛程")
        return trending

    def _export(self, content_entries: list[dict]) -> list[str]:
        if self.dry_run or settings.DRY_RUN:
            print("  ! DRY RUN 模式，跳过飞书写入")
            return []

        exporter = BitableExporter()
        record_ids = []
        for entry in content_entries:
            record_ids.extend(exporter.export(entry["result"]))
        return record_ids

    def _build_opportunities(self, matches: list[dict], trending: dict) -> list[dict]:
        """一场比赛可以拆成多条 Push 机会。"""
        opportunities = []
        raw_items = (trending or {}).get("raw_items", [])
        for match in matches:
            per_match = [self._official_opportunity(match)]
            per_match.extend(self._x_trending_opportunities(match, raw_items))
            per_match = self._dedupe_opportunities(per_match)
            opportunities.extend(per_match[: settings.MATCHDAY_MAX_PUSHES_PER_MATCH])
        print(f"  OK 构建 {len(opportunities)} 个 Push 触发机会")
        return opportunities

    def _official_opportunity(self, match: dict) -> dict:
        status = match.get("status", "")
        if status == "LIVE":
            title = "live momentum"
            scenario = "主场狂热"
            emotions = ["狂热", "愤怒"]
            priority = "high"
        elif status == "FT":
            title = "full-time reaction"
            scenario = "情怀致敬"
            emotions = ["怀旧", "感动"]
            priority = "normal"
        else:
            title = "matchday warmup"
            scenario = "社交派对"
            emotions = ["狂欢", "挑衅"]
            priority = "normal"
        return {
            "type": "matchday_" + status.lower() if status else "matchday",
            "title": title,
            "description": f"{self._match_display(match)} 官方赛程状态触发：{status or 'NS'}",
            "scenario_hint": scenario,
            "emotion_hint": emotions,
            "source": "official_schedule",
            "related_topic": "",
            "priority": priority,
            "match": match,
        }

    def _x_trending_opportunities(self, match: dict, raw_items: list[dict]) -> list[dict]:
        tokens = [token.lower() for token in self._team_tokens([match])]
        matched = []
        for item in raw_items:
            text = json.dumps(item, ensure_ascii=False).lower()
            if any(token and token.lower() in text for token in tokens):
                matched.append(item)
        if not matched:
            matched = raw_items[:1]

        opportunities = []
        for item in matched[:1]:
            content = item.get("content", "")
            topic = content[:120]
            opportunities.append({
                "type": "x_trending",
                "title": "X Sports hot angle",
                "description": f"X Sports 热点触发：{topic}",
                "scenario_hint": self._scenario_from_text(content),
                "emotion_hint": self._emotion_from_text(content),
                "source": "x_sports_trending",
                "related_topic": topic,
                "priority": "high" if self._engagement_score(item) >= 10000 else "normal",
                "match": match,
            })
        return opportunities

    def _dedupe_opportunities(self, opportunities: list[dict]) -> list[dict]:
        seen = set()
        unique = []
        for item in opportunities:
            key = (item.get("type"), item.get("related_topic", "")[:80], self._match_display(item["match"]))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _scenario_from_text(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ["var", "robbed", "ref", "penalty"]):
            return "主场狂热"
        if any(word in lowered for word in ["meme", "joke", "banter", "cry"]):
            return "玩梗群嘲"
        if any(word in lowered for word in ["legend", "goat", "last dance", "tribute"]):
            return "情怀致敬"
        if any(word in lowered for word in ["edit", "tiktok", "reels", "dance"]):
            return "短视频二创"
        return "社交派对"

    def _emotion_from_text(self, text: str) -> list[str]:
        lowered = text.lower()
        if any(word in lowered for word in ["var", "robbed", "ref"]):
            return ["愤怒", "狂热", "挑衅"]
        if any(word in lowered for word in ["meme", "joke", "banter"]):
            return ["搞笑", "嘲讽", "挑衅"]
        if any(word in lowered for word in ["goat", "legend", "tribute"]):
            return ["感动", "致敬", "怀旧"]
        return ["热血", "期待", "派对"]

    def _engagement_score(self, item: dict) -> int:
        return int(item.get("views") or 0) + int(item.get("likes") or 0) * 10 + int(item.get("retweets") or 0) * 20

    def _to_export_result(self, match: dict, content: dict, trending: dict, opportunity: dict) -> dict:
        home = match.get("team_home", {})
        away = match.get("team_away", {})
        home_code = home.get("code") or home.get("name") or "TBD"
        away_code = away.get("code") or away.get("name") or "TBD"
        score = self._score_display(home, away)
        event_context = {
            "match": {
                "teams": [home_code, away_code],
                "match_display": f"{home_code} vs {away_code}",
                "stage": match.get("stage", ""),
                "venue": match.get("venue", ""),
                "score": score,
            },
            "event": {
                "type": opportunity.get("type", "matchday"),
                "minute": 0,
                "player": "",
                "description": opportunity.get("description") or f"Matchday push: {home_code} vs {away_code}",
            },
            "api_data": match,
            "x_trending": {
                "topics": (trending or {}).get("topics", [])[:8],
                "hashtags": (trending or {}).get("hashtags", [])[:12],
            },
            "triggered_at": datetime.now().isoformat(),
        }
        return {
            "event_context": event_context,
            "content": [content],
            "generated_at": datetime.now().isoformat(),
        }

    def _save_result(self, result: dict) -> Path:
        settings.OUTPUT_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        date_label = self.match_date.replace("-", "") if self.match_date else "today"
        output_path = settings.OUTPUT_DIR / f"matchday_{date_label}_{stamp}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    def _team_tokens(self, matches: list[dict]) -> list[str]:
        tokens = []
        for match in matches:
            for side in ("team_home", "team_away"):
                team = match.get(side, {})
                tokens.extend([team.get("name", ""), team.get("code", "")])
        return [token for token in tokens if token]

    def _match_display(self, match: dict) -> str:
        home = match.get("team_home", {})
        away = match.get("team_away", {})
        return f"{home.get('code') or home.get('name') or 'TBD'} vs {away.get('code') or away.get('name') or 'TBD'}"

    def _score_display(self, home: dict, away: dict) -> str:
        if home.get("score") is None or away.get("score") is None:
            return ""
        return f"{home.get('score')}-{away.get('score')}"
