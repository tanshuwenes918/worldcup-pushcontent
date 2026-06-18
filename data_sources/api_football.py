"""
聚合数据 - 2026世界杯赛程 API 客户端
文档: https://www.juhe.cn/docs/api/id/1199
替代原 API-Football，使用国内聚合数据服务
"""
import json
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Optional

from config import settings

# 3字母国家代码 → 中文名映射（世界杯参赛队伍）
TEAM_CODE_TO_CN = {
    # A组
    "MEX": "墨西哥", "RSA": "南非", "KOR": "韩国", "CZE": "捷克",
    # B组
    "ARG": "阿根廷", "PER": "秘鲁", "DEN": "丹麦", "CMR": "喀麦隆",
    # C组
    "BRA": "巴西", "MAR": "摩洛哥", "SCO": "苏格兰", "HAI": "海地",
    # D组
    "USA": "美国", "CAN": "加拿大", "COL": "哥伦比亚", "PAR": "巴拉圭",
    # E组
    "GER": "德国", "ITA": "意大利", "ECU": "厄瓜多尔", "HON": "洪都拉斯",
    # F组
    "ESP": "西班牙", "CRO": "克罗地亚", "BOL": "玻利维亚", "TUN": "突尼斯",
    # G组
    "FRA": "法国", "URU": "乌拉圭", "NGA": "尼日利亚", "KSA": "沙特阿拉伯",
    # H组
    "ENG": "英格兰", "NED": "荷兰", "SRB": "塞尔维亚", "CRC": "哥斯达黎加",
    # I组
    "POR": "葡萄牙", "BEL": "比利时", "SEN": "塞内加尔", "IRQ": "伊拉克",
    # J组
    "JPN": "日本", "AUS": "澳大利亚", "CHI": "智利", "NOR": "挪威",
    # K组
    "POL": "波兰", "TUR": "土耳其", "UKR": "乌克兰", "WAL": "威尔士",
    # L组
    "SUI": "瑞士", "AUT": "奥地利", "IRN": "伊朗", "QAT": "卡塔尔",
}

# 中文名 → 3字母代码（反向映射）
TEAM_CN_TO_CODE = {v: k for k, v in TEAM_CODE_TO_CN.items()}

# 比赛类型映射
MATCH_TYPE_MAP = {
    "1": "小组赛",
    "2": "16强",
    "3": "8强",
    "4": "4强",
    "5": "半决赛",
    "6": "季军赛",
    "7": "决赛",
}

# 比赛状态映射
MATCH_STATUS_MAP = {
    "1": "NS",   # 未开赛
    "2": "LIVE", # 进行中
    "3": "FT",   # 已完赛
    "0": "TBD",  # 未知
}


class APIFootballClient:
    """聚合数据世界杯赛程客户端（保持原 APIFootballClient 接口兼容）"""

    BASE_URL = "https://apis.juhe.cn/fapigw/worldcup2026/schedule"

    def __init__(self):
        self.api_key = settings.JUHE_API_KEY

    def _request(self, params: dict = None) -> dict:
        """发送 API 请求"""
        url = self.BASE_URL
        query_parts = [("key", self.api_key)]
        if params:
            for k, v in params.items():
                if v is not None and v != "":
                    query_parts.append((k, str(v)))
        url = f"{url}?{urllib.parse.urlencode(query_parts)}"

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if data.get("error_code") != 0:
            raise RuntimeError(f"聚合数据 API Error: {data.get('reason', 'unknown')}")
        return data

    def _get_all_matches(self) -> list:
        """获取所有比赛（扁平化）"""
        data = self._request()
        matches = []
        for day in data.get("result", {}).get("data", []):
            for m in day.get("schedule_list", []):
                matches.append(m)
        return matches

    def search_match(self, team_a_code: str, team_b_code: str) -> Optional[dict]:
        """
        根据队伍代码搜索最近的比赛
        team_a_code/team_b_code: 3字母国家代码 (如 FRA, BRA)
        """
        try:
            cn_a = TEAM_CODE_TO_CN.get(team_a_code.upper(), team_a_code)
            cn_b = TEAM_CODE_TO_CN.get(team_b_code.upper(), team_b_code)

            all_matches = self._get_all_matches()

            for m in all_matches:
                host = m.get("host_team_name", "")
                guest = m.get("guest_team_name", "")

                # 双向匹配：A主B客 或 B主A客
                if (host == cn_a and guest == cn_b) or \
                   (host == cn_b and guest == cn_a):
                    return self._normalize_match(m)

            return None
        except Exception as e:
            print(f"  ! 聚合数据查询失败: {e}")
            return None

    def search_match_by_name(self, team_a_name: str, team_b_name: str) -> Optional[dict]:
        """
        根据中文名搜索比赛（更灵活，支持模糊匹配）
        """
        try:
            all_matches = self._get_all_matches()

            for m in all_matches:
                host = m.get("host_team_name", "")
                guest = m.get("guest_team_name", "")

                if (team_a_name in host and team_b_name in guest) or \
                   (team_b_name in host and team_a_name in guest):
                    return self._normalize_match(m)

            return None
        except Exception as e:
            print(f"  ! 聚合数据查询失败: {e}")
            return None

    def get_match_events(self, fixture_id: int) -> list:
        """
        聚合数据不提供比赛事件时间线 API
        返回空列表，事件数据由手动输入提供
        """
        return []

    def get_fixture_by_id(self, fixture_id: int) -> Optional[dict]:
        """
        聚合数据使用 team_id 作为比赛标识
        """
        try:
            all_matches = self._get_all_matches()
            for m in all_matches:
                if m.get("team_id") == str(fixture_id):
                    return self._normalize_match(m)
            return None
        except Exception:
            return None

    def get_today_matches(self) -> list:
        """获取今日所有比赛（实用方法）"""
        today = date.today().strftime("%Y-%m-%d")
        return self.get_matches_by_date(today)

    def get_matches_by_date(self, match_date: str) -> list:
        """获取指定日期的比赛，日期格式 YYYY-MM-DD。"""
        try:
            data = self._request({"date": match_date})
            matches = []
            for day in data.get("result", {}).get("data", []):
                for m in day.get("schedule_list", []):
                    matches.append(self._normalize_match(m))
            return matches
        except Exception as e:
            print(f"  ! 查询比赛日赛程失败: {e}")
            return []

    def get_matchday_matches(self, match_date: str = "") -> list:
        """比赛日入口：默认取今天，也支持 GitHub Actions 手动传日期。"""
        if match_date:
            return self.get_matches_by_date(match_date)
        return self.get_today_matches()

    def get_live_matches(self) -> list:
        """获取所有进行中的比赛"""
        try:
            all_matches = self._get_all_matches()
            live = []
            for m in all_matches:
                if m.get("match_status") == "2":  # 进行中
                    live.append(self._normalize_match(m))
            return live
        except Exception as e:
            print(f"  ! 查询进行中比赛失败: {e}")
            return []

    def _normalize_match(self, m: dict) -> dict:
        """标准化比赛数据（兼容原 API-Football 格式）"""
        host_name = m.get("host_team_name", "")
        guest_name = m.get("guest_team_name", "")
        host_code = TEAM_CN_TO_CODE.get(host_name, "")
        guest_code = TEAM_CN_TO_CODE.get(guest_name, "")

        host_score = m.get("host_team_score", "-")
        guest_score = m.get("guest_team_score", "-")
        # 处理未开赛的 "-" 比分
        if host_score == "-":
            host_score = None
        else:
            try:
                host_score = int(host_score)
            except (ValueError, TypeError):
                host_score = None

        if guest_score == "-":
            guest_score = None
        else:
            try:
                guest_score = int(guest_score)
            except (ValueError, TypeError):
                guest_score = None

        status_code = m.get("match_status", "0")
        match_type = m.get("match_type", "")

        return {
            "fixture_id": m.get("team_id"),
            "date": m.get("date_time"),
            "venue": "",  # 聚合数据不提供场馆信息
            "stage": MATCH_TYPE_MAP.get(match_type, m.get("match_type_name", "")),
            "group": m.get("group_name", ""),
            "team_home": {
                "name": host_name,
                "code": host_code,
                "logo": m.get("host_team_logo_url", ""),
                "score": host_score,
            },
            "team_away": {
                "name": guest_name,
                "code": guest_code,
                "logo": m.get("guest_team_logo_url", ""),
                "score": guest_score,
            },
            "status": MATCH_STATUS_MAP.get(status_code, m.get("match_des", "")),
            "match_des": m.get("match_des", ""),
        }

    def get_team_info(self, team_name: str) -> dict:
        """获取球队信息（聚合数据暂不提供独立球队信息接口）"""
        return {}
