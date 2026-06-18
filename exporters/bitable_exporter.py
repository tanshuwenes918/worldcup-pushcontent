"""
飞书多维表格 (Bitable) 导出器
将生成的 Push 内容写入飞书多维表格
"""
import json
import urllib.request
import subprocess
import sys
from datetime import datetime
from typing import Optional

from config import settings


class BitableExporter:
    """将 Push 内容写入飞书 Bitable"""

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
        "Hashtag建议": "Hashtag建议",
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
    }

    def __init__(self):
        self.base_token = settings.FEISHU_BASE_TOKEN
        self.table_id = settings.FEISHU_TABLE_ID

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
            "Hashtag建议": en.get("hashtags", ""),

            # 审核
            "审核状态": "🟡待审核",
            "优先级": "🔥紧急",
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

        # 关联国家 (从 teams 提取)
        teams = match.get("teams", [])
        if teams:
            fields["关联国家"] = ", ".join(teams)

        # 情绪标签 (从场景推断)
        from processors.scenario_classifier import SCENARIOS
        scenario_def = SCENARIOS.get(scenario, {})
        if scenario_def:
            fields["情绪标签"] = scenario_def.get("emotion", [])

        return fields

    def _create_record(self, fields: dict) -> Optional[str]:
        """
        通过 lark-cli 创建 Bitable 记录
        使用 subprocess 调用 lark-cli，因为它已经配置好了认证
        """
        cmd = [
            "lark-cli", "base", "+record-batch-create",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--json", json.dumps({"fields": fields}, ensure_ascii=False),
            "--as", "user",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
                encoding="utf-8",
            )

            if result.returncode == 0:
                output = json.loads(result.stdout)
                if output.get("ok"):
                    records = output.get("data", {}).get("record_id_list", [])
                    return records[0] if records else None

            # 打印错误信息
            print(f"    ✗ lark-cli error: {result.stderr or result.stdout}")
            return None

        except subprocess.TimeoutExpired:
            print("    ✗ lark-cli 调用超时")
            return None
        except Exception as e:
            print(f"    ✗ 创建记录失败: {e}")
            return None

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
            print(f"  ⚠ 飞书通知发送失败: {e}")
