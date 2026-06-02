"""
scraper/race_detail.py - レース詳細（出走馬・結果）を取得する

対象URL: https://db.netkeiba.com/race/{race_id}/
文字コード: EUC-JP
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
    weight_carried: float
    horse_weight: int | None
    horse_weight_diff: int | None
    odds: float | None
    popularity: int | None


@dataclass
class ResultData:
    horse_id: str
    finish_position: int | None
    finish_time: str
    margin: str


@dataclass
class RaceDetail:
    race_id: str
    track_condition: str
    weather: str
    distance: int
    course_type: str
    entries: list[EntryData] = field(default_factory=list)
    results: list[ResultData] = field(default_factory=list)


class RaceDetailScraper(BaseScraper):
    def fetch(self, race_id: str) -> RaceDetail:
        url = f"{RACE_DETAIL_BASE_URL}{race_id}/"
        resp = self.get(url)
        resp.encoding = "euc-jp"
        return self._parse(race_id, resp.text)

    def _parse(self, race_id: str, html: str) -> RaceDetail:
        soup = BeautifulSoup(html, "lxml")

        # 距離・馬場・天候を mainrace_data から取得
        # 例: "ダート1200m / 馬場 : 良 / ダート : 晴"
        race_data_el = soup.select_one(".mainrace_data span")
        race_data_text = race_data_el.get_text() if race_data_el else ""

        distance = 0
        m = re.search(r"(\d{3,4})m", race_data_text)
        if m:
            distance = int(m.group(1))

        course_type = "芝" if "芝" in race_data_text else "ダート"

        track_condition = ""
        m = re.search(r"馬場\s*[:：]\s*(\S+)", race_data_text)
        if m:
            track_condition = m.group(1).strip()

        weather = ""
        m = re.search(r"天候\s*[:：]\s*(\S+)", race_data_text)
        if m:
            weather = m.group(1).strip()
        else:
            # 「ダート : 晴」「芝 : 曇」のパターン
            m = re.search(r"(?:ダート|芝)\s*[:：]\s*(\S+)", race_data_text)
            if m:
                weather = m.group(1).strip()

        detail = RaceDetail(
            race_id=race_id,
            track_condition=track_condition,
            weather=weather,
            distance=distance,
            course_type=course_type,
        )

        # 結果テーブル（列の位置で取得）
        table = soup.select_one("table.race_table_01")
        if not table:
            return detail

        # ヘッダー行から列インデックスを特定
        header_row = table.select_one("tr")
        if not header_row:
            return detail

        headers = [th.get_text(strip=True) for th in header_row.select("th")]

        def col_idx(name: str) -> int:
            for i, h in enumerate(headers):
                if name in h:
                    return i
            return -1

        idx_pos    = col_idx("着")
        idx_frame  = col_idx("枠")
        idx_num    = col_idx("馬番")
        idx_weight = col_idx("斤")
        idx_time   = col_idx("タイム")
        idx_margin = col_idx("着差")
        idx_odds   = col_idx("単勝")
        idx_pop    = col_idx("人気")
        idx_body   = col_idx("馬体重")

        for row in table.select("tr")[1:]:
            cols = row.select("td")
            if len(cols) < 5:
                continue

            def get(idx: int) -> str:
                if idx < 0 or idx >= len(cols):
                    return ""
                return cols[idx].get_text(strip=True)

            # 馬IDと馬名
            horse_link = row.select_one("a[href*='/horse/']")
            if not horse_link:
                continue
            horse_id_m = re.search(r"/horse/(\w+)/", horse_link["href"])
            horse_id = horse_id_m.group(1) if horse_id_m else ""
            horse_name = horse_link.get_text(strip=True)

            # 騎手
            jockey_link = row.select_one("a[href*='/jockey/']")
            jockey_name = jockey_link.get_text(strip=True) if jockey_link else ""

            # 調教師
            trainer_link = row.select_one("a[href*='/trainer/']")
            trainer_name = trainer_link.get_text(strip=True) if trainer_link else ""

            # 馬体重
            horse_weight, horse_weight_diff = None, None
            body_raw = get(idx_body)
            hw_m = re.match(r"(\d+)\(([+-]?\d+)\)", body_raw)
            if hw_m:
                horse_weight = int(hw_m.group(1))
                horse_weight_diff = int(hw_m.group(2))

            def to_int(s: str) -> int | None:
                try:
                    return int(re.sub(r"[^\d-]", "", s)) if s else None
                except ValueError:
                    return None

            def to_float(s: str) -> float | None:
                try:
                    return float(s) if s else None
                except ValueError:
                    return None

            entry = EntryData(
                horse_id=horse_id,
                horse_name=horse_name,
                horse_number=to_int(get(idx_num)) or 0,
                frame_number=to_int(get(idx_frame)) or 0,
                jockey_name=jockey_name,
                trainer_name=trainer_name,
                weight_carried=to_float(get(idx_weight)) or 0.0,
                horse_weight=horse_weight,
                horse_weight_diff=horse_weight_diff,
                odds=to_float(get(idx_odds)),
                popularity=to_int(get(idx_pop)),
            )
            detail.entries.append(entry)

            result = ResultData(
                horse_id=horse_id,
                finish_position=to_int(get(idx_pos)),
                finish_time=get(idx_time),
                margin=get(idx_margin),
            )
            detail.results.append(result)

        return detail
