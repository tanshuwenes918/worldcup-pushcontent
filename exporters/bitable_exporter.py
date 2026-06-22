"""
飞书多维表格 (Bitable) 导出器
将生成的 Push 内容写入飞书多维表格
"""
import json
import re
import urllib.request
import subprocess
import sys
import urllib.error
import shutil
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from config import settings
from data_sources.api_football import team_display_cn, team_name_to_cn


class BitableExporter:
    """将 Push 内容写入飞书 Bitable"""

    # Bitable 情绪标签字段实际选项（10个）
    EMOTION_OPTIONS = {
        "热血", "期待", "怀念", "狂欢", "戏谑",
        "温情", "挑衅", "悲伤", "派对", "遗憾",
    }
    # LLM 非标准输出 → 最接近的合法选项
    EMOTION_ALIASES = {
        # 中文非标准 → 合法选项
        "怀旧": "怀念", "感动": "温情", "忧伤": "悲伤",
        "狂热": "热血", "嘲讽": "戏谑", "愤怒": "挑衅",
        "搞笑": "戏谑", "神圣": "热血", "紧张": "期待",
        "预热": "期待", "实时": "热血", "争议": "挑衅",
        "二创": "戏谑", "复盘": "怀念", "赛后": "怀念",
        "情绪": "温情",
        # 英文 LLM 输出 → 合法中文选项 (安全网)
        "nostalgic": "怀念", "nostalgia": "怀念",
        "moved": "温情", "emotional": "温情",
        "proud": "热血", "pride": "热血",
        "hype": "热血", "excited": "热血", "passion": "热血",
        "frustration": "遗憾", "disappointed": "遗憾",
        "party": "派对", "celebration": "狂欢",
        "victory": "狂欢", "anthem": "热血",
        "sad": "悲伤",
        "provocative": "挑衅", "dramatic": "热血",
        "playful": "戏谑", "banter": "戏谑",
        "hope": "期待",
    }

    # Bitable 字段映射 (代码字段名 → Bitable 字段名)
    FIELD_MAP = {
        # 赛事信息
        "对阵": "对阵",
        "比赛日期": "比赛日期",
        "赛事阶段": "赛事阶段",
        "触发事件": "触发事件",
        "事件类型": "事件类型",
        "关联球员": "关联球员",
        "关联国家": "关联国家",
        "场景类型": "场景类型",
        "适用对象/热点": "适用对象/热点",
        "情绪标签": "情绪标签",
        # 英文内容
        "Push Title (EN)": "Push Title (EN)",
        "Push Desc (EN)": "Push Desc (EN)",
        # 中文
        "Push Title (ZH)": "Push Title (ZH)",
        "Push Desc (ZH)": "Push Desc (ZH)",
        # 西班牙语
        "Push Title (ES)": "Push Title (ES)",
        "Push Desc (ES)": "Push Desc (ES)",
        # 马来语
        "Push Title (MS)": "Push Title (MS)",
        "Push Desc (MS)": "Push Desc (MS)",
        # 菲律宾语
        "Push Title (FIL)": "Push Title (FIL)",
        "Push Desc (FIL)": "Push Desc (FIL)",
        # 葡萄牙语(葡萄牙)
        "Push Title (PT-PT)": "Push Title (PT-PT)",
        "Push Desc (PT-PT)": "Push Desc (PT-PT)",
        # 葡萄牙语(巴西)
        "Push Title (PT-BR)": "Push Title (PT-BR)",
        "Push Desc (PT-BR)": "Push Desc (PT-BR)",
        # AIGC & Hashtag
        "AIGC Prompt JSON": "AIGC Prompt JSON",
        "Hashtag 建议": "Hashtag 建议",
        # 审核
        "审核状态": "审核状态",
        "优先级": "优先级",
        "审核备注": "审核备注",
    }

    # 事件类型映射 (英文代码 → 中文显示名)
    EVENT_TYPE_MAP = {
        "goal": "进球",
        "red_card": "红牌",
        "penalty": "点球",
        "var_controversy": "VAR争议",
        "upset": "爆冷",
        "injury": "伤退",
        "hat_trick": "帽子戏法",
        "own_goal": "乌龙",
        "last_minute_goal": "绝杀",
        "penalty_save": "扑点",
        "milestone": "里程碑",
        "matchday": "比赛日",
        "matchday_ns": "赛前预热",
        "matchday_live": "实时赛况",
        "matchday_ft": "赛后复盘",
        "x_trending": "X热点",
    }

    def __init__(self):
        self.base_token = settings.FEISHU_BASE_TOKEN
        self.table_id = settings.FEISHU_TABLE_ID
        self.app_id = settings.FEISHU_APP_ID
        self.app_secret = settings.FEISHU_APP_SECRET

    def export(self, result: dict) -> list:
        """
        将完整生成结果写入 Bitable

        result 结构:
        {
            "event_context": {...},
            "content": [{"scenario": ..., "en": {...}, "translations": {...}}, ...],
        }

        返回: 创建的 record_id 列表
        """
        event_ctx = result.get("event_context", {})
        content_list = result.get("content", [])

        record_ids = []

        for content_entry in content_list:
            record_fields = self._build_record_fields(
                event_ctx=event_ctx,
                content=content_entry,
            )

            record_id = self._create_record(record_fields)
            if record_id:
                record_ids.append(record_id)

        return record_ids

    def _build_record_fields(self, event_ctx: dict, content: dict) -> dict:
        """构建单条 Bitable 记录的字段值"""
        match = event_ctx.get("match", {})
        event = event_ctx.get("event", {})
        en = content.get("en", {})
        translations = content.get("translations", {})
        scenario = content.get("scenario", "")

        match_display = self._match_display_cn(event_ctx)

        fields = {
            # 赛事信息
            "对阵": match_display,
            "赛事阶段": match.get("stage", "小组赛"),
            "触发事件": event.get("description", ""),
            "关联球员": event.get("player", ""),
            "场景类型": scenario,
            "适用对象/热点": en.get("applicable_object", ""),

            # 事件类型 (multi-select)
            "事件类型": [self.EVENT_TYPE_MAP.get(event.get("type", ""), event.get("type", ""))],

            # 英文内容
            "Push Title (EN)": en.get("push_title", ""),
            "Push Desc (EN)": en.get("push_description", ""),

            # AIGC Prompt & Hashtags
            "AIGC Prompt JSON": self._build_aigc_prompt_text(event_ctx, content, match_display),
            "Hashtag 建议": en.get("hashtags", ""),

            # 审核
            "审核状态": "🟡待审核",
            "优先级": self._calculate_priority(event_ctx, content),
            "审核备注": "",
        }

        # 比赛日期 (从 API 数据获取)
        api_data = event_ctx.get("api_data", {})
        if api_data.get("date"):
            timestamp = self._to_bitable_timestamp(api_data["date"])
            if timestamp is not None:
                fields["比赛日期"] = timestamp

        # 多语言内容
        lang_field_map = {
            "ZH": ("Push Title (ZH)", "Push Desc (ZH)"),
            "ES": ("Push Title (ES)", "Push Desc (ES)"),
            "MS": ("Push Title (MS)", "Push Desc (MS)"),
            "FIL": ("Push Title (FIL)", "Push Desc (FIL)"),
            "PT-PT": ("Push Title (PT-PT)", "Push Desc (PT-PT)"),
            "PT-BR": ("Push Title (PT-BR)", "Push Desc (PT-BR)"),
        }
        for lang_code, (title_field, desc_field) in lang_field_map.items():
            lang_content = translations.get(lang_code, {})
            fields[title_field] = lang_content.get("push_title", "")
            fields[desc_field] = lang_content.get("push_description", "")

        # 情绪标签优先使用 ZH 翻译（中文），回退到 EN（英文别名安全网）
        # EN 输出 "nostalgic/moved/proud" 等英文词，_normalize_emotions 以中文为主
        zh = translations.get("ZH", {})
        emotion_tags = zh.get("emotion_tags", []) or en.get("emotion_tags", [])
        if emotion_tags:
            fields["情绪标签"] = self._normalize_emotions(emotion_tags)

        # 关联国家 (从 teams 提取)
        teams = self._teams_cn(event_ctx)
        if teams:
            fields["关联国家"] = ", ".join(teams)

        if "情绪标签" not in fields:
            # 情绪标签 (从场景推断, select 单选用字符串)
            from processors.scenario_classifier import SCENARIOS
            scenario_def = SCENARIOS.get(scenario, {})
            if scenario_def:
                emotions = scenario_def.get("emotion", [])
                fields["情绪标签"] = self._normalize_emotions(emotions)

        return fields

    def _match_display_cn(self, event_ctx: dict) -> str:
        """Build the table-facing match display using Chinese team names."""
        match = event_ctx.get("match", {})
        api_data = event_ctx.get("api_data", {})
        home = api_data.get("team_home", {})
        away = api_data.get("team_away", {})
        if home or away:
            return f"{team_display_cn(home)} vs {team_display_cn(away)}"

        teams = match.get("teams", [])
        if isinstance(teams, list) and len(teams) >= 2:
            return f"{team_display_cn(teams[0])} vs {team_display_cn(teams[1])}"

        display = str(match.get("match_display", "") or "").strip()
        parts = [part.strip() for part in re.split(r"\bvs\b", display, maxsplit=1, flags=re.I)]
        if len(parts) == 2 and all(parts):
            return f"{team_name_to_cn(parts[0])} vs {team_name_to_cn(parts[1])}"
        return team_name_to_cn(display) or display

    def _teams_cn(self, event_ctx: dict) -> list[str]:
        match = event_ctx.get("match", {})
        api_data = event_ctx.get("api_data", {})
        home = api_data.get("team_home", {})
        away = api_data.get("team_away", {})
        if home or away:
            return [team_display_cn(home), team_display_cn(away)]

        teams = match.get("teams", [])
        if not isinstance(teams, list):
            return []

        normalized = []
        for team in teams:
            name = team_display_cn(team)
            if name and name not in normalized:
                normalized.append(name)
        return normalized

    def _build_aigc_prompt_text(self, event_ctx: dict, content: dict, match_display: str) -> str:
        """Convert the structured AIGC prompt into plain text under 100 words."""
        prompt = self._preferred_aigc_prompt(content)
        event = event_ctx.get("event", {})

        if isinstance(prompt, str) and prompt.strip():
            parsed_prompt = self._parse_prompt_json_string(prompt)
            if isinstance(parsed_prompt, dict):
                prompt = parsed_prompt
            else:
                text = self._plain_prompt_string(prompt)
                return self._truncate_words(text, 100)

        if isinstance(prompt, dict):
            genre = self._prompt_part(prompt.get("genre"), ("primary", "secondary", "fusion"))
            mood = self._prompt_part(prompt.get("mood"), ("primary", "secondary", "intensity"))
            instrumentation = self._prompt_part(prompt.get("instrumentation"), ("core", "accent"))
            lyrics = prompt.get("lyrics", {}) if isinstance(prompt.get("lyrics"), dict) else {}
            theme = lyrics.get("theme") or event.get("description", "")
            genre_text = genre or "high-energy football"
            text = (
                f"Create {self._article_for(genre_text)} {genre_text} AI anthem for {match_display}. "
                f"Mood: {mood or 'fan hype'}. Theme: {theme}. "
                f"Use {instrumentation or 'stadium drums, crowd chants, and a replayable chorus'}. "
                "Keep it safe, punchy, mobile-first, and social-native."
            )
        else:
            trigger = event.get("description", "")
            text = (
                f"Create a high-energy football AI anthem for {match_display}. "
                f"Use the trigger angle: {trigger}. "
                "Keep it chant-ready, social-native, punchy, and safe."
            )

        return self._truncate_words(text, 100)

    def _parse_prompt_json_string(self, value: str):
        text = value.strip()
        if not text.startswith(("{", "[")):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _plain_prompt_string(self, value: str) -> str:
        text = re.sub(r"[{}\[\]\"]+", "", value.strip())
        return re.sub(r"\s+", " ", text).strip()

    def _article_for(self, text: str) -> str:
        return "an" if text[:1].lower() in {"a", "e", "i", "o", "u"} else "a"

    def _preferred_aigc_prompt(self, content: dict):
        en = content.get("en", {})
        if en.get("aigc_prompt"):
            return en.get("aigc_prompt")
        for lang_content in content.get("translations", {}).values():
            if lang_content.get("aigc_prompt"):
                return lang_content.get("aigc_prompt")
        return {}

    def _prompt_part(self, value, preferred_keys: tuple[str, ...] = ()) -> str:
        if isinstance(value, dict):
            keys = preferred_keys or tuple(value.keys())
            parts = [self._prompt_part(value.get(key)) for key in keys]
            return ", ".join(part for part in parts if part)
        if isinstance(value, list):
            parts = [self._prompt_part(item) for item in value]
            return ", ".join(part for part in parts if part)
        return str(value or "").strip()

    def _truncate_words(self, text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]).rstrip(" ,.;:") + "."

    def _to_bitable_timestamp(self, value) -> Optional[int]:
        """Convert common datetime strings to a Feishu-compatible unix ms timestamp."""
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            number = int(value)
            return number if number > 10_000_000_000 else number * 1000

        text = str(value).strip()
        if not text:
            return None

        tz = ZoneInfo(settings.TIMEZONE or "Asia/Shanghai")
        candidates = [
            lambda v: datetime.fromisoformat(v.replace("Z", "+00:00")),
            lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
            lambda v: datetime.strptime(v, "%Y-%m-%d"),
        ]
        for parser in candidates:
            try:
                dt = parser(text)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                return int(dt.timestamp() * 1000)
            except Exception:
                continue
        return None

    def _normalize_emotions(self, emotions) -> list[str]:
        """多选字段只写入表里已有的情绪选项，避免创建脏选项。"""
        if isinstance(emotions, str):
            parts = [p.strip() for p in emotions.replace("，", ",").split(",")]
        else:
            parts = [str(p).strip() for p in emotions if str(p).strip()]

        normalized = []
        for part in parts:
            value = self.EMOTION_ALIASES.get(part, part)
            if value in self.EMOTION_OPTIONS and value not in normalized:
                normalized.append(value)
        return normalized or ["期待"]

    # ── 优先级映射 ──
    # 高优先级事件类型（进球/红牌/点球等直接决定比赛走向的事件）
    HIGH_PRIORITY_EVENTS = {
        "goal", "red_card", "penalty", "var_controversy", "upset",
        "hat_trick", "own_goal", "last_minute_goal", "matchday_live",
    }
    # 中优先级事件类型（有话题性但不直接决定胜负）
    MEDIUM_PRIORITY_EVENTS = {"milestone", "penalty_save", "injury", "matchday_ft"}
    # 高优先级赛事阶段
    HIGH_PRIORITY_STAGES = {"决赛", "半决赛", "4强"}

    def _calculate_priority(self, event_ctx: dict, content: dict) -> str:
        """
        根据事件类型 + 赛事阶段动态计算优先级

        优先级分级:
        - 🔥紧急: 高优先级事件 或 关键阶段比赛
        - ⭐高: 中等优先级事件
        - 📌普通: 其他
        """
        event = event_ctx.get("event", {})
        match = event_ctx.get("match", {})
        event_type = event.get("type", "")
        stage = match.get("stage", "")

        # 关键阶段比赛直接最高优先级
        if stage in self.HIGH_PRIORITY_STAGES:
            return "🔥紧急"

        # 按事件类型分级
        if event_type in self.HIGH_PRIORITY_EVENTS:
            return "🔥紧急"
        if event_type in self.MEDIUM_PRIORITY_EVENTS:
            return "⭐高"

        return "📌普通"

    def _create_record(self, fields: dict) -> Optional[str]:
        """
        通过 lark-cli 创建 Bitable 记录
        使用 subprocess 调用 lark-cli，因为它已经配置好了认证
        """
        if self.app_id and self.app_secret:
            return self._create_record_via_api(fields)

        lark_cli = self._resolve_lark_cli()
        if not lark_cli:
            print("    ERROR 未找到 lark-cli。请安装全局 lark-cli，或在 .env 设置 LARK_CLI_PATH。")
            return None

        # 写入临时文件避免命令行长度限制（lark-cli 要求相对路径）
        import tempfile, os
        tmp_name = f"_bitable_tmp_{os.getpid()}.json"
        tmp_path = os.path.join(os.getcwd(), tmp_name)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(fields, f, ensure_ascii=False)

        cmd = [
            lark_cli, "base", "+record-upsert",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--json", f"@{tmp_name}",
            "--as", "user",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                encoding="utf-8", errors="replace", shell=True,
            )

            if result.returncode == 0:
                output = json.loads(result.stdout)
                if output.get("ok"):
                    record = output.get("data", {}).get("record", {})
                    # upsert 返回 record_id_list
                    ids = record.get("record_id_list", [])
                    if ids:
                        return ids[0]
                    # 兼容单条 record_id
                    rid = record.get("record_id", "")
                    return rid if rid else None

            # 打印错误信息
            stderr = result.stderr.strip() if result.stderr else ""
            stdout = result.stdout.strip() if result.stdout else ""
            print(f"    ERROR lark-cli error (code={result.returncode}):")
            if stderr:
                print(f"      stderr: {stderr[:300]}")
            if stdout:
                print(f"      stdout: {stdout[:300]}")
            return None

        except subprocess.TimeoutExpired:
            print("    ERROR lark-cli 调用超时")
            return None
        except Exception as e:
            print(f"    ERROR 创建记录失败: {e}")
            return None
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _resolve_lark_cli(self) -> str:
        """Resolve local lark-cli without coupling to a vendor-specific path."""
        if settings.LARK_CLI_PATH:
            return settings.LARK_CLI_PATH
        return shutil.which("lark-cli.cmd") or shutil.which("lark-cli") or ""

    def _create_record_via_api(self, fields: dict) -> Optional[str]:
        """GitHub Actions 使用飞书开放平台凭证直接写入 Bitable。"""
        try:
            token = self._get_tenant_access_token()
            url = (
                "https://open.feishu.cn/open-apis/bitable/v1/apps/"
                f"{self.base_token}/tables/{self.table_id}/records"
            )
            payload = json.dumps({"fields": fields}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if body.get("code") == 0:
                return body.get("data", {}).get("record", {}).get("record_id")
            print(f"    ERROR 飞书 API 写入失败: {str(body)[:300]}")
            return None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            print(f"    ERROR 飞书 API HTTP {e.code}: {detail}")
            return None
        except Exception as e:
            print(f"    ERROR 飞书 API 创建记录失败: {e}")
            return None

    def _get_tenant_access_token(self) -> str:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = json.dumps({
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        token = body.get("tenant_access_token")
        if not token:
            raise RuntimeError(f"无法获取 tenant_access_token: {str(body)[:200]}")
        return token

    def notify_feishu_group(self, message: str):
        """通过飞书 Webhook 通知运营群"""
        webhook_url = settings.FEISHU_WEBHOOK_URL
        if not webhook_url:
            return

        payload = {
            "msg_type": "text",
            "content": {"text": message},
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception as e:
            print(f"  ! 飞书通知发送失败: {e}")
