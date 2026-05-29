"""
scraper/race_detail.py - レース詳細（出走馬・結果）を取得する

対象URL: https://db.netkeiba.com/race/{race_id}/
"""

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from config import RACE_DETAIL_BASE_URL
from scraper.base import BaseScraper


@dataclass
class EntryData:
    horse_id: str
    horse_name: str
    horse_number: int
    frame_number: int
    jockey_name: str
    trainer_name: str
    weight_carried: float   # 斤量
    horse_weight: int | None
    horse_weight_diff: int | None
    odds: float | None
    popularity: int | None


@dataclass
class ResultData:
    horse_id: str
    finish_position: int | None   # 着順（取消・除外はNone）
    finish_time: str              # タイム文字列 "1:34.5"
    margin: str                   # 着差


@dataclass
class RaceDetail:
    race_id: str
    track_condition: str   # 良/稍重/重/不良
    weather: str
    entries: list[EntryData] = field(default_factory=list)
    results: list[ResultData] = field(default_factory=list)


class RaceDetailScraper(BaseScraper):
    def fetch(self, race_id: str) -> RaceDetail:
        url = f"{RACE_DETAIL_BASE_URL}{race_id}/"
        resp = self.get(url)
        return self._parse(race_id, resp.text)

    def _parse(self, race_id: str, html: str) -> RaceDetail:
        soup = BeautifulSoup(html, "lxml")

        # 馬場・天気
        race_data = soup.select_one(".RaceData01") or soup.select_one(".mainrace_data")
        race_data_text = race_data.get_text() if race_data else ""
        track_condition = self._extract(r"馬場:(\S+)", race_data_text) or self._extract(r"(良|稍重|重|不良)", race_data_text) or ""
        weather = self._extract(r"天候:(\S+)", race_data_text) or self._extract(r"天気:(\S+)", race_data_text) or ""

        detail = RaceDetail(race_id=race_id, track_condition=track_condition, weather=weather)

        # 出走表・結果テーブル
        table = soup.select_one("table.race_table_01") or soup.select_one(".ResultTableWrap table")
        if not table:
            return detail

        headers = [th.get_text(strip=True) for th in table.select("tr:first-child th")]

        for row in table.select("tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.select("td")]
            if not cols:
                continue

            def col(name: str) -> str:
                try:
                    return cols[headers.index(name)] if name in headers else ""
                except (ValueError, IndexError):
                    return ""

            horse_link = row.select_one("a[href*='/horse/']")
            if not horse_link:
                continue
            horse_id_m = re.search(r"/horse/(\w+)/", horse_link["href"])
            horse_id = horse_id_m.group(1) if horse_id_m else ""

            jockey_link = row.select_one("a[href*='/jockey/']")
            jockey_name = jockey_link.get_text(strip=True) if jockey_link else col("騎手")

            trainer_link = row.select_one("a[href*='/trainer/']")
            trainer_name = trainer_link.get_text(strip=True) if trainer_link else col("調教師")

            def to_int(s: str) -> int | None:
                try:
                    return int(s)
                except (ValueError, TypeError):
                    return None

            def to_float(s: str) -> float | None:
                try:
                    return float(s)
                except (ValueError, TypeError):
                    return None

            horse_weight_raw = col("馬体重")
            horse_weight, horse_weight_diff = None, None
            hw_m = re.match(r"(\d+)\(([+-]?\d+)\)", horse_weight_raw)
            if hw_m:
                horse_weight = int(hw_m.group(1))
                horse_weight_diff = int(hw_m.group(2))

            entry = EntryData(
                horse_id=horse_id,
                horse_name=col("馬名") or (horse_link.get_text(strip=True)),
                horse_number=to_int(col("馬番")) or 0,
                frame_number=to_int(col("枠番")) or 0,
                jockey_name=jockey_name,
                trainer_name=trainer_name,
                weight_carried=to_float(col("斤量")) or 0.0,
                horse_weight=horse_weight,
                horse_weight_diff=horse_weight_diff,
                odds=to_float(col("単勝")),
                popularity=to_int(col("人気")),
            )
            detail.entries.append(entry)

            finish_pos_raw = col("着順")
            result = ResultData(
                horse_id=horse_id,
                finish_position=to_int(finish_pos_raw),
                finish_time=col("タイム"),
                margin=col("着差"),
            )
            detail.results.append(result)

        return detail

    def _extract(self, pattern: str, text: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None
