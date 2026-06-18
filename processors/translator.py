"""
多语言翻译与文化适配引擎
不是直译，而是"文化适配重写"
"""
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import settings
from processors.content_generator import ContentGenerator


# ── 语言配置 ──
LANGUAGES = {
    "EN": {"name": "English", "flag": "🇬🇧"},
    "ZH": {"name": "中文", "flag": "🇨🇳"},
    "ES": {"name": "Español", "flag": "🇪🇸"},
    "MS": {"name": "Bahasa Melayu", "flag": "🇲🇾"},
    "FIL": {"name": "Filipino", "flag": "🇵🇭"},
    "PT-PT": {"name": "Português (Portugal)", "flag": "🇵🇹"},
    "PT-BR": {"name": "Português (Brasil)", "flag": "🇧🇷"},
}

# ── 每种语言的文化适配指令 ──
LANGUAGE_GUIDELINES = {
    "ZH": """中文文化适配要求:
1. 融入中文球迷圈梗（如"姆总监""凯恩无冠""退钱哥""日耳曼战车"等）
2. 语气偏微博/虎扑风，简短有力，带点"发疯文学"味
3. 可使用中文互联网流行语（如"破防了""赢麻了""格局打开"）
4. Push Title 保持 15-30 字符（中文字符）
5. AIGC Prompt 的 lyrics 字段用中文歌词意象""",

    "ES": """西班牙语文化适配要求:
1. 使用拉美足球文化用语，热情奔放
2. 可融入当地俚语（如 "boludo", "ché", "pibe", "golazo"）
3. 对于巴西/阿根廷相关的赛事要特别热情
4. AIGC Prompt 的 lyrics 字段融入西语足球文化意象（如 "la pelota no se mancha"）""",

    "MS": """马来语文化适配要求:
1. 口语化，融入东南亚球迷文化
2. 适度混入英语借词（Manglish 风格：lah, kan, wei）
3. 语气轻松友好，适合 TikTok 年轻用户
4. AIGC Prompt 可保持英语为主，但 theme 用马来语描述""",

    "FIL": """菲律宾语文化适配要求:
1. Taglish 风格（菲律宾语 + 英语混搭），这是菲律宾年轻人的自然表达方式
2. 可使用 "pare", "bro", "grabe", "solid" 等口语
3. 非常适合 TikTok/社交媒体调性
4. AIGC Prompt 保持英语为主，但 theme 可加入 Taglish""",

    "PT-PT": """葡萄牙（欧洲）语文化适配要求:
1. 偏正式的足球用语
2. C 罗 / 葡萄牙国家队情怀导向
3. 使用 "craque", "seleção", "futebol arte" 等表达
4. 与巴西葡萄牙语区分，不要用巴西俚语""",

    "PT-BR": """巴西葡萄牙语文化适配要求:
1. 极度热情，融入巴西足球文化
2. 可融入 funk/samba/carnaval 文化元素
3. 使用 "craque", "gol de placa", "futebol arte", "joga bonito" 等表达
4. AIGC Prompt 的 lyrics 字段融入巴西文化意象
5. 与欧洲葡萄牙语明确区分""",
}


class MultiLanguageTranslator:
    """多语言文化适配翻译器"""

    def __init__(self):
        self.generator = ContentGenerator()

    def translate_all(self, en_content: dict, scenario: str, event_context: dict) -> dict:
        """
        并行将英文基准内容适配为所有语言版本

        返回: {
            "ZH": {"push_title": ..., "push_description": ..., ...},
            ...
        }
        """
        target_langs = ["ZH", "ES", "MS", "FIL", "PT-PT", "PT-BR"]
        results = {}

        def _do_translate(lang_code: str) -> tuple[str, dict]:
            try:
                translated = self._translate_single(
                    en_content=en_content,
                    target_lang=lang_code,
                    scenario=scenario,
                    event_context=event_context,
                )
                # 校验翻译结果
                warnings = self.generator._validate_content(
                    translated, context_label=lang_code
                )
                self.generator._log_validation(warnings, context_label=lang_code)
                return lang_code, translated
            except Exception as e:
                print(f"    ! {lang_code} 翻译失败: {e}，使用英文基准版")
                return lang_code, {
                    "push_title": en_content.get("push_title", ""),
                    "push_description": en_content.get("push_description", ""),
                    "aigc_prompt": en_content.get("aigc_prompt", {}),
                    "hashtags": en_content.get("hashtags", ""),
                }

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_do_translate, lang): lang
                for lang in target_langs
            }
            for future in as_completed(futures):
                lang_code, translated = future.result()
                results[lang_code] = translated

        return results

    def _translate_single(self, en_content: dict, target_lang: str,
                          scenario: str, event_context: dict) -> dict:
        """翻译单个语言版本"""
        lang_info = LANGUAGES.get(target_lang, {})
        guidelines = LANGUAGE_GUIDELINES.get(target_lang, "")

        prompt = f"""Adapt the following English World Cup Push content into {lang_info.get('name', target_lang)} ({lang_info.get('flag', '')}).

## Original English Content
```json
{json.dumps(en_content, ensure_ascii=False, indent=2)}
```

## Scenario: {scenario}
## Match: {event_context.get('match', {}).get('match_display', '')}
## Event: {event_context.get('event', {}).get('description', '')}

## Cultural Adaptation Guidelines
{guidelines}

## Requirements
1. This is NOT literal translation — it's cultural adaptation rewrite
2. Incorporate local football culture memes and expressions
3. Maintain the same emotional intensity and provocativeness
4. Push Title: keep 15-30 characters
5. Push Description: keep 40-80 characters
6. AIGC Prompt: adapt the lyrics theme and key_imagery to {lang_info.get('name', target_lang)} culture
7. Hashtags: add local fan community hashtags alongside the universal ones

## Output Format
Return a JSON object with exactly these fields:
```json
{{
    "push_title": "adapted title in {lang_info.get('name', target_lang)}",
    "push_description": "adapted description in {lang_info.get('name', target_lang)}",
    "aigc_prompt": <same structure as input, with adapted lyrics fields>,
    "hashtags": "adapted hashtags with local tags"
}}
```

Return ONLY the JSON object."""

        response = self.generator._call_llm(prompt, system_role="translator")

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
                return json.loads(json_str)
            raise
