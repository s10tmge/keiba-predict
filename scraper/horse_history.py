"""
scraper/horse_history.py - 馬の過去成績を取得する

対象URL: https://db.netkeiba.com/horse/{horse_id}/
過去レース履歴（直近20走）をhorse_historiesテーブルに保存する。
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from scraper.base import BaseScraper

HORSE_BASE_URL = "https://db.netkeiba.com/horse/result/"


@dataclass
class HorseRaceRecord:
    horse_id: str
    race_date: str          # YYYY-MM-DD
    venue: str
    race_name: str
    race_class: str
    course_type: str        # 芝/ダート
    distance: int
    track_condition: str    # 良/稍重/重/不良
    headcount: int
    frame_number: int | None
    horse_number: int | None
    popularity: int | None
    odds: float | None
    finish_position: int | None
    finish_time: str
    last_3f: float | None
    horse_weight: int | None
    horse_weight_diff: int | None
    jockey_name: str


class HorseHistoryScraper(BaseScraper):
    def fetch(self, horse_id: str) -> list[HorseRaceRecord]:
        url = f"{HORSE_BASE_URL}{horse_id}/"
        try:
            resp = self.get(url)
            resp.encoding = "euc-jp"
            return self._parse(horse_id, resp.text)
        except Exception:
            return []

    def _parse(self, horse_id: str, html: str) -> list[HorseRaceRecord]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.select_one("table.db_h_race_results, table.race_table_01")
        if not table:
            return []

        headers = [th.get_text(strip=True) for th in table.select("tr:first-child th")]

        def col(name: str) -> int:
            for i, h in enumerate(headers):
                if name in h:
                    return i
            return -1

        idx_date  = col("日付")
        idx_venue = col("開催")
        idx_name  = col("レース名")
        idx_hc    = col("頭数")
        idx_frame = col("枠番")
        idx_num   = col("馬番")
        idx_pop   = col("人気")
        idx_odds  = col("オッズ")
        idx_pos   = col("着順")
        idx_time  = col("タイム")
        idx_3f    = col("上り")
        idx_body  = col("馬体重")
        idx_dist  = col("距離")
        idx_cond  = col("馬場")
        idx_jock  = col("騎手")

        records = []
        for row in table.select("tr")[1:]:
            cols = row.select("td")
            if len(cols) < 5:
                continue

            def get(idx: int) -> str:
                if idx < 0 or idx >= len(cols):
                    return ""
                return cols[idx].get_text(strip=True)

            def to_int(s: str) -> int | None:
                s = re.sub(r"[^\d-]", "", s)
                try: return int(s) if s else None
                except: return None

            def to_float(s: str) -> float | None:
                try: return float(s) if s else None
                except: return None

            # 日付
            date_raw = get(idx_date)
            date_m = re.search(r"(\d{4})/(\d{2})/(\d{2})", date_raw)
            if not date_m:
                continue
            race_date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"

            # 距離・コース
            dist_raw = get(idx_dist)
            course_type = "芝" if "芝" in dist_raw else "ダート" if "ダ" in dist_raw else ""
            dist_m = re.search(r"(\d{3,4})", dist_raw)
            distance = int(dist_m.group(1)) if dist_m else 0

            # 障害除外
            if "障" in dist_raw or "障" in get(idx_name):
                continue

            # 馬体重
            horse_weight, horse_weight_diff = None, None
            body_raw = get(idx_body)
            hw_m = re.match(r"(\d+)\(([+-]?\d+)\)", body_raw)
            if hw_m:
                horse_weight = int(hw_m.group(1))
                horse_weight_diff = int(hw_m.group(2))

            # 着順（中止・除外はNone）
            pos_raw = get(idx_pos)
            finish_position = to_int(pos_raw) if pos_raw.isdigit() else None

            # 会場
            venue_raw = get(idx_venue)
            venue = re.sub(r"\d+回|\d+日目", "", venue_raw).strip()

            records.append(HorseRaceRecord(
                horse_id=horse_id,
                race_date=race_date,
                venue=venue,
                race_name=get(idx_name),
                race_class=self._parse_class(get(idx_name)),
                course_type=course_type,
                distance=distance,
                track_condition=get(idx_cond),
                headcount=to_int(get(idx_hc)) or 0,
                frame_number=to_int(get(idx_frame)),
                horse_number=to_int(get(idx_num)),
                popularity=to_int(get(idx_pop)),
                odds=to_float(get(idx_odds)),
                finish_position=finish_position,
                finish_time=get(idx_time),
                last_3f=to_float(get(idx_3f)),
                horse_weight=horse_weight,
                horse_weight_diff=horse_weight_diff,
                jockey_name=get(idx_jock),
            ))

            # 直近20走で打ち切り
            if len(records) >= 20:
                break

        return records

    def _parse_class(self, race_name: str) -> str:
        for kw in ["G1", "G2", "G3", "新馬", "未勝利", "1勝", "2勝", "3勝", "オープン", "リステッド"]:
            if kw in race_name:
                return kw
        return ""
