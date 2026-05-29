"""
scraper/base.py - スクレイピング基底クラス

robots.txt確認・スリープ・リトライ処理を共通化する。
"""

import random
import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

from config import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF,
    SLEEP_MAX,
    SLEEP_MIN,
    USER_AGENTS,
)


class BaseScraper:
    def __init__(self):
        self.session = requests.Session()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def _get_headers(self) -> dict:
        return {"User-Agent": random.choice(USER_AGENTS)}

    def _sleep(self):
        time.sleep(random.uniform(SLEEP_MIN, SLEEP_MAX))

    def _check_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots_cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:
                return True  # 取得失敗時はアクセス許可とみなす
            self._robots_cache[base] = rp
        ua = self._get_headers()["User-Agent"]
        return self._robots_cache[base].can_fetch(ua, url)

    def get(self, url: str) -> requests.Response:
        if not self._check_robots(url):
            raise PermissionError(f"robots.txt により {url} へのアクセスは禁止されています")

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                self._sleep()
                resp = self.session.get(
                    url, headers=self._get_headers(), timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                return resp
            except requests.RequestException as e:
                last_exc = e
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"[RETRY {attempt + 1}/{MAX_RETRIES}] {e} — {wait}秒後に再試行")
                time.sleep(wait)

        raise RuntimeError(f"最大リトライ回数到達: {url}") from last_exc
