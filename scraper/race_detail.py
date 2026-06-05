"""
scraper/race_detail.py - レース詳細（出走馬・結果・払戻）を取得する

対象URL: https://db.netkeiba.com/race/{race_id}/
文字コード: EUC-JP
除外: 障害レース・新馬戦は呼び出し前にフィルタ済み
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
    last_3f: float | None        # 上がり3ハロン


@dataclass
class ResultData:
    horse_id: str
    finish_position: int | None
    finish_time: str
    margin: str


@dataclass
class PayoutData:
    bet_type: str
    combination: str
    payout: int
    popularity: int | None


@dataclass
class RaceDetail:
    race_id: str
    track_condition: str
    weather: str
    distance: int
    course_type: str
    race_class: str              # G1/G2/G3/L/OP/3勝/2勝/1勝/未勝利
    grade: str                   # G1/G2/G3/L/OP
    entries: list[EntryData] = field(default_factory=list)
    results: list[ResultData] = field(default_factory=list)
    payouts: list[PayoutData] = field(default_factory=list)


class RaceDetailScraper(BaseScraper):
    def fetch(self, race_id: str) -> RaceDetail:
        url = f"{RACE_DETAIL_BASE_URL}{race_id}/"
        resp = self.get(url)
        resp.encoding = "euc-jp"
        return self._parse(race_id, resp.text)

    def _parse(self, race_id: str, html: str) -> RaceDetail:
        soup = BeautifulSoup(html, "lxml")

        # ---- コース・距離・馬場・天候 ----
        race_data_el = soup.select_one(".mainrace_data span")
        race_data_text = race_data_el.get_text(" ", strip=True) if race_data_el else ""

        distance = 0
        m = re.search(r"(\d{3,4})m", race_data_text)
        if m:
            distance = int(m.group(1))

        course_type = "芝" if "芝" in race_data_text else "ダート"

        # 馬場状態: 「馬場：良」「馬場:稍重」など
        track_condition = ""
        m = re.search(r"馬場\s*[：:]\s*([^\s/　]+)", race_data_text)
        if m:
            track_condition = m.group(1).strip()

        # 天候: 「天候：晴」「天気：曇」など
        weather = ""
        m = re.search(r"天[候気]\s*[：:]\s*([^\s/　]+)", race_data_text)
        if m:
            weather = m.group(1).strip()

        # ---- レースクラス・グレード ----
        race_class, grade = self._parse_class(soup)

        detail = RaceDetail(
            race_id=race_id,
            track_condition=track_condition,
            weather=weather,
            distance=distance,
            course_type=course_type,
            race_class=race_class,
            grade=grade,
        )

        # ---- 出走馬テーブル ----
        table = soup.select_one("table.race_table_01")
        if not table:
            return detail

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
        idx_3f     = col_idx("上り")

        for row in table.select("tr")[1:]:
            cols = row.select("td")
            if len(cols) < 5:
                continue

            def get(idx: int) -> str:
                if idx < 0 or idx >= len(cols):
                    return ""
                return cols[idx].get_text(strip=True)

            horse_link = row.select_one("a[href*='/horse/']")
            if not horse_link:
                continue
            horse_id_m = re.search(r"/horse/(\w+)/", horse_link["href"])
            horse_id = horse_id_m.group(1) if horse_id_m else ""
            horse_name = horse_link.get_text(strip=True)

            jockey_link = row.select_one("a[href*='/jockey/']")
            jockey_name = jockey_link.get_text(strip=True) if jockey_link else ""

            trainer_link = row.select_one("a[href*='/trainer/']")
            trainer_name = trainer_link.get_text(strip=True) if trainer_link else ""

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

            # 上がり3ハロン
            last_3f = to_float(get(idx_3f))

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
                last_3f=last_3f,
            )
            detail.entries.append(entry)

            result = ResultData(
                horse_id=horse_id,
                finish_position=to_int(get(idx_pos)),
                finish_time=get(idx_time),
                margin=get(idx_margin),
            )
            detail.results.append(result)

        detail.payouts = self._parse_payouts(soup)
        return detail

    def _parse_class(self, soup: BeautifulSoup) -> tuple[str, str]:
        """レース名からクラスとグレードを抽出する。"""
        title_el = soup.select_one(".mainrace_data h1, .race_name")
        title = title_el.get_text(strip=True) if title_el else ""

        grade = ""
        if "(G1)" in title or "（G1）" in title: grade = "G1"
        elif "(G2)" in title or "（G2）" in title: grade = "G2"
        elif "(G3)" in title or "（G3）" in title: grade = "G3"
        elif "(L)" in title or "（L）" in title or "リステッド" in title: grade = "L"

        race_class = grade if grade else ""

        # クラス情報はmainrace_dataのテキストから
        data_el = soup.select_one(".mainrace_data p")
        data_text = data_el.get_text(" ", strip=True) if data_el else ""

        for kw in ["3勝クラス", "2勝クラス", "1勝クラス", "未勝利", "オープン", "新馬"]:
            if kw in data_text:
                race_class = kw
                break

        return race_class, grade

    def _parse_payouts(self, soup: BeautifulSoup) -> list[PayoutData]:
        payouts = []
        for table in soup.select("table.pay_table_01, table.pay_table_02"):
            for row in table.select("tr"):
                cells = row.select("td")
                if len(cells) < 2:
                    continue
                bet_type_el = row.select_one("th")
                if not bet_type_el:
                    continue
                bet_type_text = bet_type_el.get_text(strip=True)

                combinations = [s.strip() for s in cells[0].get_text(separator="\n").split("\n") if s.strip()]
                payouts_raw  = [s.strip().replace(",", "") for s in cells[1].get_text(separator="\n").split("\n") if s.strip()]
                pops_raw     = [s.strip() for s in cells[2].get_text(separator="\n").split("\n") if s.strip()] if len(cells) > 2 else []

                for i, combo in enumerate(combinations):
                    payout_str = payouts_raw[i] if i < len(payouts_raw) else ""
                    pop_str    = pops_raw[i] if i < len(pops_raw) else ""
                    try:
                        payout_val = int(re.sub(r"[^\d]", "", payout_str))
                    except (ValueError, TypeError):
                        continue
                    try:
                        pop_val = int(re.sub(r"[^\d]", "", pop_str)) if pop_str else None
                    except (ValueError, TypeError):
                        pop_val = None
                    combo = re.sub(r"[　\s]", "", combo)
                    payouts.append(PayoutData(
                        bet_type=bet_type_text,
                        combination=combo,
                        payout=payout_val,
                        popularity=pop_val,
                    ))
        return payouts
