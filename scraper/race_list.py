"""
scraper/race_list.py - 開催日のレース一覧を取得する

対象URL: https://race.netkeiba.com/top/race_list.html?kaisai_date=YYYYMMDD
"""

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from config import EXCLUDE_RACE_KEYWORDS, RACE_LIST_URL
from scraper.base import BaseScraper


@dataclass
class RaceInfo:
    race_id: str        # netkeiba形式の12桁ID (例: 202401010101)
    date: date
    venue: str
    race_number: int
    race_name: str
    course_type: str    # 芝 / ダート
    distance: int       # メートル
    race_class: str


class RaceListScraper(BaseScraper):
    def fetch(self, target_date: date) -> list[RaceInfo]:
        """指定日のレース一覧を取得し、除外フィルター適用後のリストを返す。"""
        date_str = target_date.strftime("%Y%m%d")
        url = f"{RACE_LIST_URL}?kaisai_date={date_str}"
        resp = self.get(url)
        return self._parse(resp.text, target_date)

    def _parse(self, html: str, target_date: date) -> list[RaceInfo]:
        soup = BeautifulSoup(html, "lxml")
        races: list[RaceInfo] = []

        for race_list in soup.select(".RaceList_DataItem"):
            link = race_list.select_one("a[href*='/race/']")
            if not link:
                continue

            href = link["href"]
            m = re.search(r"/race/(\d{12})", href)
            if not m:
                continue
            race_id = m.group(1)

            race_name = (race_list.select_one(".RaceName") or race_list.select_one(".ItemTitle") or link).get_text(strip=True)
            if self._should_exclude(race_name):
                continue

            # 競馬場名（race_idの5〜6桁目から推定）
            venue_code = race_id[4:6]
            venue = self._venue_name(venue_code)

            race_number_text = race_list.select_one(".RaceNum")
            race_number = int(re.search(r"\d+", race_number_text.get_text()).group()) if race_number_text else 0

            # コース・距離情報
            course_text = (race_list.select_one(".RaceData01") or race_list.select_one(".Item03") or link).get_text()
            course_type, distance = self._parse_course(course_text)

            races.append(RaceInfo(
                race_id=race_id,
                date=target_date,
                venue=venue,
                race_number=race_number,
                race_name=race_name,
                course_type=course_type,
                distance=distance,
                race_class="",
            ))

        return races

    def _should_exclude(self, race_name: str) -> bool:
        return any(kw in race_name for kw in EXCLUDE_RACE_KEYWORDS)

    def _parse_course(self, text: str) -> tuple[str, int]:
        course_type = "芝" if "芝" in text else "ダート"
        m = re.search(r"(\d{3,4})m", text, re.IGNORECASE)
        distance = int(m.group(1)) if m else 0
        return course_type, distance

    def _venue_name(self, code: str) -> str:
        mapping = {
            "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
            "05": "東京", "06": "中山", "07": "中京", "08": "京都",
            "09": "阪神", "10": "小倉",
        }
        return mapping.get(code, f"不明({code})")
