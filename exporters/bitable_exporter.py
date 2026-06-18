"""
飞书多维表格 (Bitable) 导出器
将生成的 Push 内容写入飞书多维表格
"""
import json
import urllib.request
import subprocess
import sys
import urllib.error
import shutil
from datetime import datetime
from typing import Optional

from config import settings


class BitableExporter:
    """将 Push 内容写入飞书 Bitable"""

    EMOTION_OPTIONS = {
        "嘲讽", "狂欢", "怀旧", "愤怒", "感动",
        "搞笑", "挑衅", "神圣", "忧伤", "狂热",
    }
    EMOTION_ALIASES = {
        "预热": "狂欢",
        "期待": "狂欢",
        "派对": "狂欢",
        "紧张": "狂热",
        "实时": "狂热",
        "争议": "愤怒",
        "二创": "搞笑",
        "复盘": "怀旧",
        "赛后": "怀旧",
        "情绪": "感动",
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

        # 合并所有语言的 AIGC Prompt
        aigc_prompts = {"EN": en.get("aigc_prompt", {})}
        for lang, lang_content in translations.items():
            aigc_prompts[lang] = lang_content.get("aigc_prompt", {})

        fields = {
            # 赛事信息
            "对阵": match.get("match_display", ""),
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
            "AIGC Prompt JSON": json.dumps(aigc_prompts, ensure_ascii=False, indent=2),
            "Hashtag 建议": en.get("hashtags", ""),

            # 审核
            "审核状态": "🟡待审核",
            "优先级": self._calculate_priority(event_ctx, content),
            "审核备注": "",
        }

        # 比赛日期 (从 API 数据获取)
        api_data = event_ctx.get("api_data", {})
        if api_data.get("date"):
            fields["比赛日期"] = api_data["date"]

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

        # 情绪标签优先使用 LLM 输出，回退到场景定义
        emotion_tags = en.get("emotion_tags", [])
        if emotion_tags:
            fields["情绪标签"] = self._normalize_emotions(emotion_tags)

        # 关联国家 (从 teams 提取)
        teams = match.get("teams", [])
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
        return normalized or ["狂热"]

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
