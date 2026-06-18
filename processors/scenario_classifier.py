"""
场景分类器 - 根据比赛事件判断触发的内容场景
"""
import json
from pathlib import Path

# 球员梗标签库
PLAYER_MEME_TAGS_FILE = Path(__file__).resolve().parent.parent / "data" / "player_memes.json"

# ── 场景定义 ──
SCENARIOS = {
    "玩梗群嘲": {
        "id": 1,
        "description": "TikTok 病毒传播主阵地 - 嘲讽、恶搞、群嘲",
        "triggers": ["underperformance", "controversy", "penalty_miss", "var_favor"],
        "emotion": ["嘲讽", "搞笑", "挑衅"],
    },
    "情怀致敬": {
        "id": 2,
        "description": "IG/X 高赞共情收割机 - 致敬、里程碑、逆转",
        "triggers": ["legend_milestone", "last_dance", "comeback", "goal_celebration"],
        "emotion": ["感动", "怀旧", "神圣"],
    },
    "社交派对": {
        "id": 3,
        "description": "赛前预热、看球派对、群聊对战",
        "triggers": ["pre_match", "host_nation", "weekend_match", "group_stage"],
        "emotion": ["狂欢", "挑衅", "搞笑"],
    },
    "短视频二创": {
        "id": 4,
        "description": "TikTok/Reels BGM 驱动 - 卡点、鬼畜、Reaction",
        "triggers": ["spectacular_goal", "funny_moment", "dramatic_reaction", "prediction"],
        "emotion": ["搞笑", "狂热", "嘲讽"],
    },
    "主场狂热": {
        "id": 5,
        "description": "东道主、VAR争议、爆冷、赛场突发",
        "triggers": ["host_nation_match", "var_controversy", "upset", "stadium_incident"],
        "emotion": ["愤怒", "狂热", "狂欢"],
    },
    "遗憾怀念": {
        "id": 6,
        "description": "伤退、落选、已故传奇的怀念",
        "triggers": ["injury", "squad_omission", "elimination", "memorial"],
        "emotion": ["忧伤", "怀旧", "感动"],
    },
}

# ── 事件类型到场景的映射规则 ──
EVENT_SCENARIO_MAP = {
    "goal": {
        "default": "情怀致敬",
        "conditions": {
            "传奇球员进球": "情怀致敬",
            "知名球员进球打脸": "情怀致敬",
            "世界波/倒钩": "短视频二创",
            "搞笑庆祝": "玩梗群嘲",
        },
    },
    "red_card": {
        "default": "玩梗群嘲",
        "conditions": {
            "争议红牌": "主场狂热",
            "愚蠢红牌": "玩梗群嘲",
        },
    },
    "penalty": {
        "default": "玩梗群嘲",
        "conditions": {
            "点球罚失": "玩梗群嘲",
            "争议点球": "主场狂热",
        },
    },
    "var_controversy": {
        "default": "主场狂热",
    },
    "upset": {
        "default": "主场狂热",
        "conditions": {
            "大热门出局": "玩梗群嘲",
            "黑马逆袭": "主场狂热",
        },
    },
    "injury": {
        "default": "遗憾怀念",
    },
    "hat_trick": {
        "default": "情怀致敬",
    },
    "own_goal": {
        "default": "玩梗群嘲",
    },
    "last_minute_goal": {
        "default": "情怀致敬",
        "conditions": {
            "绝杀": "情怀致敬",
            "被绝杀": "玩梗群嘲",
        },
    },
    "penalty_save": {
        "default": "情怀致敬",
    },
    "milestone": {
        "default": "情怀致敬",
    },
}

# ── 东道主国家 ──
HOST_NATIONS = ["USA", "US", "CAN", "MEX", "墨西哥", "美国", "加拿大"]


class ScenarioClassifier:
    """根据比赛事件上下文，分类到一个或多个场景"""

    def __init__(self):
        self.player_memes = self._load_player_memes()

    def classify(self, event_context: dict) -> list:
        """
        分类事件到场景

        返回: [{"scenario": str, "confidence": float, "reason": str}, ...]
        """
        event_type = event_context.get("event", {}).get("type", "")
        player = event_context.get("event", {}).get("player", "")
        teams = event_context.get("match", {}).get("teams", [])
        stage = event_context.get("match", {}).get("stage", "")

        results = []

        # 1. 基于事件类型的基础分类
        event_map = EVENT_SCENARIO_MAP.get(event_type, {})
        base_scenario = event_map.get("default", "玩梗群嘲")

        # 2. 上下文增强
        is_host_match = any(t in HOST_NATIONS for t in teams)
        player_tags = self._get_player_tags(player)

        reason_parts = [f"事件: {event_type}"]

        # 特殊条件判断
        if event_type in ("goal", "penalty", "upset", "last_minute_goal"):
            # 检查是否涉及东道主
            if is_host_match:
                results.append({
                    "scenario": "主场狂热",
                    "confidence": 0.7,
                    "reason": f"东道主比赛 + {event_type}",
                })
                reason_parts.append("东道主比赛")

            # 检查球员梗标签
            if "负面梗" in player_tags or "隐身" in player_tags:
                scenario = "玩梗群嘲"
            elif "传奇" in player_tags or "GOAT" in player_tags:
                scenario = "情怀致敬"
            else:
                scenario = base_scenario
        elif event_type == "var_controversy":
            scenario = "主场狂热"
            reason_parts.append("VAR 争议")
        elif event_type == "injury":
            scenario = "遗憾怀念"
            reason_parts.append("球员伤退")
        else:
            scenario = base_scenario

        # 主场景
        if not any(r["scenario"] == scenario for r in results):
            results.append({
                "scenario": scenario,
                "confidence": 0.9,
                "reason": " | ".join(reason_parts),
            })

        # 附加场景（短视频二创几乎总是可以附加的）
        if event_type in ("goal", "red_card", "own_goal", "var_controversy",
                          "last_minute_goal", "hat_trick"):
            if not any(r["scenario"] == "短视频二创" for r in results):
                results.append({
                    "scenario": "短视频二创",
                    "confidence": 0.6,
                    "reason": f"视觉冲击事件 ({event_type}) 适合二创",
                })

        return results

    def _get_player_tags(self, player_name: str) -> list:
        """获取球员的梗标签"""
        if not player_name:
            return []
        player_name_lower = player_name.lower()
        for name, info in self.player_memes.items():
            if player_name_lower in name.lower() or name.lower() in player_name_lower:
                return info.get("tags", [])
        return []

    def _load_player_memes(self) -> dict:
        """加载球员梗标签库"""
        if PLAYER_MEME_TAGS_FILE.exists():
            try:
                with open(PLAYER_MEME_TAGS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
