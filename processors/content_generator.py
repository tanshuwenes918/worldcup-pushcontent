"""
内容生成器 - 调用 LLM 生成 Push Title/Description/AIGC Prompt/Hashtags
"""
import json
import re
import time
import urllib.error
import urllib.request
from typing import Optional

from config import settings


# ── 场景 → AIGC Prompt 风格映射 ──
SCENARIO_STYLE_MAP = {
    "玩梗群嘲": {
        "genre_primary": "Comedy / Satire",
        "genre_options": ["Bossa Nova", "Country Comedy", "Punk Rock", "Emo Rock"],
        "mood": "sarcastic, playful, mocking",
        "bpm_range": [100, 180],
        "vocal_tone": "mocking, comedic",
        "social_focus": "TikTok meme potential, singable chorus",
    },
    "情怀致敬": {
        "genre_primary": "Epic / Emotional",
        "genre_options": ["Orchestral Pop", "R&B Ballad", "Brazilian Funk-Trap"],
        "mood": "epic, emotional, triumphant",
        "bpm_range": [70, 140],
        "vocal_tone": "soaring, emotional",
        "social_focus": "IG/X tribute content, cinematic feel",
    },
    "社交派对": {
        "genre_primary": "Party / Social",
        "genre_options": ["Irish Pub-Rock", "EDM Festival", "Electronic Rap"],
        "mood": "energetic, competitive, celebratory",
        "bpm_range": [120, 150],
        "vocal_tone": "rowdy, hype",
        "social_focus": "group sing-along, party atmosphere",
    },
    "短视频二创": {
        "genre_primary": "BGM / Edit-friendly",
        "genre_options": ["Phonk", "Glitch-Hop", "Hyperpop", "Cinematic Rock"],
        "mood": "dramatic, mysterious, goofy",
        "bpm_range": [130, 180],
        "vocal_tone": "varies by sub-type",
        "social_focus": "TikTok/Reels BGM, sync-friendly beats",
    },
    "主场狂热": {
        "genre_primary": "Stadium / Aggressive",
        "genre_options": ["Heavy Metal", "Stadium Hip-Hop", "EDM", "Mariachi-Trap"],
        "mood": "furious, euphoric, explosive",
        "bpm_range": [128, 170],
        "vocal_tone": "screaming, chanting, aggressive",
        "social_focus": "stadium chants, bass-heavy drops",
    },
    "遗憾怀念": {
        "genre_primary": "Melancholic / Tribute",
        "genre_options": ["Alt-Rock Ballad", "Synth-Pop", "Blues", "Acoustic R&B"],
        "mood": "melancholic, nostalgic, divine",
        "bpm_range": [60, 100],
        "vocal_tone": "soulful, ethereal",
        "social_focus": "memorial tributes, emotional resonance",
    },
}


class ContentGenerator:
    """LLM 内容生成器"""

    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    def generate(self, event_context: dict, scenario: str) -> dict:
        """
        生成英文基准版的 Push 内容

        返回:
        {
            "push_title": str,
            "push_description": str,
            "aigc_prompt": dict (structured JSON),
            "hashtags": str,
            "applicable_object": str,
        }
        """
        style = SCENARIO_STYLE_MAP.get(scenario, SCENARIO_STYLE_MAP["玩梗群嘲"])
        match_info = event_context.get("match", {})
        event_info = event_context.get("event", {})

        prompt = self._build_generation_prompt(
            match_info=match_info,
            event_info=event_info,
            scenario=scenario,
            style=style,
        )

        response = self._call_llm(prompt, system_role="content_generator")

        # 解析 LLM 返回的 JSON
        try:
            content = json.loads(response)
        except json.JSONDecodeError:
            # 尝试从 markdown code block 中提取
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
                content = json.loads(json_str)
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
                content = json.loads(json_str)
            else:
                raise ValueError(f"无法解析 LLM 输出: {response[:200]}")

        # 校验生成内容
        warnings = self._validate_content(content, context_label="EN基准")
        self._log_validation(warnings, context_label="EN基准")

        return content

    def _build_generation_prompt(self, match_info, event_info, scenario, style) -> str:
        """构建内容生成的 prompt"""
        return f"""You are the Vanso World Cup Push Content Generator.
Generate viral push notification content for an AI music generation app during the 2026 FIFA World Cup.

## Current Event
- Match: {match_info.get('match_display', 'Unknown')}
- Stage: {match_info.get('stage', 'Group Stage')}
- Venue: {match_info.get('venue', 'Unknown')}
- Score: {match_info.get('score', 'Unknown')}
- Event: {event_info.get('description', 'Unknown')}
- Player: {event_info.get('player', 'Unknown')}
- Minute: {event_info.get('minute', 'Unknown')}'

## Target Scenario: {scenario}
Style Guidelines:
- Genre: {style['genre_primary']} (options: {', '.join(style['genre_options'])})
- Mood: {style['mood']}
- BPM Range: {style['bpm_range'][0]}-{style['bpm_range'][1]}
- Vocal Tone: {style['vocal_tone']}
- Social Focus: {style['social_focus']}

## Output Requirements
Return a JSON object with exactly these fields:

```json
{{
    "push_title": "15-30 chars, starts with emoji, short/punchy/provocative, action-oriented",
    "push_description": "40-80 chars, emotional trigger + call-to-action to generate a song",
    "aigc_prompt": {{
        "title_hint": "suggested song title",
        "genre": {{
            "primary": "main genre",
            "secondary": "sub-genre or fusion",
            "fusion": null
        }},
        "mood": {{
            "primary": "primary mood",
            "secondary": "secondary mood",
            "intensity": "low/medium/high"
        }},
        "tempo": {{
            "bpm_range": [{style['bpm_range'][0]}, {style['bpm_range'][1]}],
            "feel": "rhythmic feel description",
            "rhythm_pattern": "specific rhythm pattern"
        }},
        "instrumentation": {{
            "core": ["core instrument 1", "core instrument 2"],
            "accent": ["accent instrument"],
            "exclude": ["instruments to avoid"]
        }},
        "vocal": {{
            "style": "vocal style",
            "gender": "male/female/any",
            "language": "en",
            "tone": "vocal tone",
            "reference": "artist reference for style"
        }},
        "lyrics": {{
            "theme": "lyrical theme in one sentence",
            "key_imagery": ["imagery 1", "imagery 2", "imagery 3"],
            "tone": "lyrical tone",
            "structure": "song structure",
            "must_include": ["element 1", "element 2"],
            "must_avoid": ["profanity", "personal attacks"]
        }},
        "production": {{
            "length_seconds": [60, 90],
            "energy_curve": "how energy builds through the song",
            "mix_style": "production aesthetic",
            "hook_strength": "high/medium - how catchy the hook should be"
        }},
        "social_optimization": {{
            "tiktok_friendly": true,
            "meme_potential": "high/medium/low",
            "duet_friendly": true,
            "trending_audio_style": true
        }}
    }},
    "hashtags": "#VansoWorldCup26 #MyAnthem2026 + 3-5 scenario/player/country specific hashtags",
    "applicable_object": "who this targets, e.g. '姆巴佩(隐身/姆总监)'"
}}
```

## Style Rules
- Push Title: NO marketing speak. Sound like a fired-up fan, not a brand.
- Push Description: Must create urgency to click and generate a song NOW.
- AIGC Prompt: Must have vivid, specific imagery that produces viral-worthy lyrics.
- Hashtags: Layer 1 (brand) + Layer 2 (event) + Layer 3 (country) + Layer 4 (player meme) + Layer 5 (scenario)

## LANGUAGE ENFORCEMENT (CRITICAL)
- ALL text fields (push_title, push_description, aigc_prompt, hashtags, applicable_object) MUST be in ENGLISH ONLY.
- push_title and push_description characters: must be ASCII/Latin alphabet. NO Chinese, Japanese, Korean, Arabic, or any non-Latin script.
- Even if the player/team is non-English, use their English name (e.g., "Vinicius" not "维尼修斯").
- If you output any Chinese or non-English content, the result will be REJECTED.

Return ONLY the JSON object, no extra text."""

    def _call_llm(self, prompt: str, system_role: str = "content_generator",
                  max_retries: int = 3) -> str:
        """调用 LLM API，含自动重试和错误处理"""
        system_prompts = {
            "content_generator": "You are a world-class social media content strategist and AI music prompt engineer specializing in football/soccer culture. You output only valid JSON. ALL content you generate MUST be in ENGLISH only — never use Chinese or any other language.",
            "translator": "You are a football culture localization expert. You adapt content culturally, not translate literally. You output only valid JSON.",
            "matchday_push_generator": "You are a World Cup matchday push editor for an AI music app. You merge official match data and social trend signals, then output only valid JSON for EN, ZH, ES, MS, FIL, PT-PT, and PT-BR.",
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompts.get(system_role, system_prompts["content_generator"])},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "response_format": {"type": "json_object"},
        }

        data = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/v1/chat/completions"

        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    },
                    method="POST",
                )

                with urllib.request.urlopen(req, timeout=90) as resp:
                    status = resp.getcode()
                    body = resp.read().decode()

                    if status != 200:
                        raise urllib.error.HTTPError(
                            url, status, f"HTTP {status}", resp.headers, None)

                    result = json.loads(body)

                # 校验响应结构
                if "choices" not in result or not result["choices"]:
                    raise ValueError(f"LLM 响应缺少 choices: {str(result)[:200]}")

                content = result["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("LLM 返回空内容")

                return content

            except urllib.error.HTTPError as e:
                last_error = e
                status_code = e.code if hasattr(e, 'code') else 0
                if status_code == 429:
                    # Rate limit — 等待更久
                    wait = 2 ** attempt + 3
                elif status_code >= 500:
                    wait = 2 ** attempt
                else:
                    raise  # 4xx (非429) 不重试，直接抛
                if attempt < max_retries:
                    print(f"  ! LLM 调用失败 (HTTP {status_code})，{wait}s 后重试 ({attempt}/{max_retries})...")
                    time.sleep(wait)

            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = e
                wait = 2 ** attempt
                if attempt < max_retries:
                    print(f"  ! LLM 网络错误: {e}，{wait}s 后重试 ({attempt}/{max_retries})...")
                    time.sleep(wait)

            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                wait = 2 ** attempt
                if attempt < max_retries:
                    print(f"  ! LLM 响应解析失败: {e}，{wait}s 后重试 ({attempt}/{max_retries})...")
                    time.sleep(wait)

        raise RuntimeError(f"LLM 调用失败（{max_retries} 次重试后）: {last_error}")

    # ── 内容验证 ──
    REQUIRED_BRAND_HASHTAGS = ["#VansoWorldCup26", "#MyAnthem2026"]
    AIGC_PROMPT_TOP_KEYS = [
        "title_hint", "genre", "mood", "tempo", "instrumentation",
        "vocal", "lyrics", "production", "social_optimization",
    ]

    def _validate_content(self, content: dict, context_label: str = "") -> list[str]:
        """
        校验 LLM 输出内容的质量

        返回: 警告列表（空列表表示全部通过）
        """
        warnings = []
        label = f"[{context_label}] " if context_label else ""

        # 1. 语言检测：push_title/push_description 不得含 CJK 字符
        for field in ["push_title", "push_description"]:
            text = content.get(field, "")
            if not isinstance(text, str) or not text.strip():
                warnings.append(f"{label}{field} 为空或非字符串")
                continue
            cjk_chars = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]', text)
            if cjk_chars:
                warnings.append(
                    f"{label}{field} 包含非英文内容: "
                    f"\"{text[:60]}\" (CJK: {cjk_chars[:5]})"
                )

        # 2. push_title 长度检查 (15-30 chars 为理想范围)
        title = content.get("push_title", "")
        if isinstance(title, str) and title.strip():
            tlen = len(title)
            if tlen < 10:
                warnings.append(f"{label}push_title 过短 ({tlen} chars): \"{title}\"")
            elif tlen > 50:
                warnings.append(f"{label}push_title 过长 ({tlen} chars): \"{title[:60]}...\"")

        # 3. push_description 长度检查 (40-80 chars 为理想范围)
        desc = content.get("push_description", "")
        if isinstance(desc, str) and desc.strip():
            dlen = len(desc)
            if dlen < 20:
                warnings.append(f"{label}push_description 过短 ({dlen} chars): \"{desc}\"")
            elif dlen > 120:
                warnings.append(f"{label}push_description 过长 ({dlen} chars): \"{desc[:60]}...\"")

        # 4. hashtags 必须包含品牌标签
        hashtags = content.get("hashtags", "")
        if isinstance(hashtags, str):
            missing = [t for t in self.REQUIRED_BRAND_HASHTAGS if t not in hashtags]
            if missing:
                warnings.append(f"{label}hashtags 缺少品牌标签: {missing}")
            if not hashtags.startswith("#"):
                warnings.append(f"{label}hashtags 不以 # 开头: \"{hashtags[:40]}\"")
        else:
            warnings.append(f"{label}hashtags 不是字符串: {type(hashtags).__name__}")

        # 5. aigc_prompt 结构完整性
        aigc = content.get("aigc_prompt")
        if not isinstance(aigc, dict):
            warnings.append(f"{label}aigc_prompt 不是 dict: {type(aigc).__name__}")
        else:
            missing_keys = [k for k in self.AIGC_PROMPT_TOP_KEYS if k not in aigc]
            if missing_keys:
                warnings.append(f"{label}aigc_prompt 缺少顶层键: {missing_keys}")

        # 6. applicable_object 检查
        ao = content.get("applicable_object", "")
        if isinstance(ao, str) and ao.strip():
            cjk_ao = re.findall(r'[\u4e00-\u9fff]', ao)
            if cjk_ao:
                warnings.append(
                    f"{label}applicable_object 包含中文: \"{ao[:50]}\" "
                    f"(基准版应为英文，翻译版才用本地语言)"
                )

        return warnings

    def _log_validation(self, warnings: list[str], context_label: str = ""):
        """打印校验警告"""
        if not warnings:
            print(f"  OK 内容校验通过{' ' + context_label if context_label else ''}")
            return
        print(f"  ! 内容校验发现 {len(warnings)} 个问题{' ' + context_label if context_label else ''}:")
        for w in warnings:
            print(f"    - {w}")
