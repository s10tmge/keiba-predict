"""
scraper/race_list.py - 開催日のレース一覧を取得する

対象URL: https://db.netkeiba.com/race/list/YYYYMMDD/
"""

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup

from config import EXCLUDE_RACE_KEYWORDS, JRA_VENUE_CODES, RACE_LIST_BASE_URL
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
        url = f"{RACE_LIST_BASE_URL}{date_str}/"
        resp = self.get(url)
        return self._parse(resp.text, target_date)

    def _parse(self, html: str, target_date: date) -> list[RaceInfo]:
        soup = BeautifulSoup(html, "lxml")
        races: list[RaceInfo] = []

        # db.netkeiba.com/race/list/ のリンクパターン: /race/202301060201/
        for link in soup.find_all("a", href=re.compile(r"/race/\d{12}/")):
            href = link["href"]
            m = re.search(r"/race/(\d{12})/", href)
            if not m:
                continue
            race_id = m.group(1)

            race_name = link.get_text(strip=True)

            # レース番号はリンクテキストか周辺テキストから取得
            # race_idの末尾2桁がレース番号
            race_number = int(race_id[10:12])

            if self._should_exclude(race_name):
                continue

            # 競馬場コードはrace_idの5〜6桁目
            venue_code = race_id[4:6]
            if venue_code not in JRA_VENUE_CODES:
                continue  # 地方競馬を除外
            venue = self._venue_name(venue_code)

            # コース・距離は周辺のtdから取得を試みる
            parent_td = link.find_parent("td")
            course_text = ""
            if parent_td:
                row = parent_td.find_parent("tr")
                if row:
                    course_text = row.get_text()

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
