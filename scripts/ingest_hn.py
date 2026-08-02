"""
ingest_hn.py — HackerNews ingest via Firebase API
Fetches today's top stories with score > 350. No RSS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, UTC

import requests

from config import hn_config
from db_utils import hn_exists, insert_hn
from ingest_base import run_parallel

HN_TOP  = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"


def main() -> None:
    cfg        = hn_config()
    min_score  = cfg.get("filter", {}).get("min_score", 350)
    max_age_h  = cfg.get("filter", {}).get("max_age_hours", 48)
    top_n      = cfg.get("fetch", {}).get("top_n", 200)
    workers    = cfg.get("fetch", {}).get("workers", 10)

    print(f"ingest_hn: top {top_n}, min_score={min_score}, max_age={max_age_h}h")

    resp = requests.get(HN_TOP, timeout=15)
    resp.raise_for_status()
    ids = resp.json()[:top_n]

    def fetch_and_process(hn_id: int) -> None:
        try:
            r = requests.get(HN_ITEM.format(hn_id), timeout=10)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return
        if not data:
            return
        item_id = str(data.get("id", ""))
        if not item_id or hn_exists(item_id):
            return
        if data.get("score", 0) < min_score:
            return
        unix_time = data.get("time", 0)
        if datetime.fromtimestamp(unix_time, tz=UTC) < datetime.now(UTC) - timedelta(hours=max_age_h):
            return
        created_at = datetime.fromtimestamp(unix_time, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        insert_hn(
            hn_id=item_id,
            title=data.get("title", ""),
            url=data.get("url"),
            score=data["score"],
            by=data.get("by", ""),
            descendants=data.get("descendants", 0),
            created_at=created_at,
        )
        print(f"  [{data['score']}] {data.get('title', '')[:70]}")

    tasks = [dict(hn_id=i) for i in ids]
    run_parallel(tasks, fetch_and_process, max_workers=workers, label_key="hn_id")

    print("ingest_hn: done")


if __name__ == "__main__":
    main()
