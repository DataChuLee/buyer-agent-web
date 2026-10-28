"""
warmup_crawler.py
=================
서버 부팅 시 인기 키워드 × 셀러 × 가격대 조합을 사전에 크롤·인덱싱한다.
사용자 요청이 도착했을 때 ChromaDB 에 이미 데이터가 있으면 Playwright 크롤(5~30s/셀러)을
건너뛰고 RAG + LLM 응답만 실행되어 콜드 스타트 latency 가 5초 미만으로 줄어든다.

- 키워드 정의: `backend/warmup_keywords.yaml`
- 이미 레지스트리 TTL(24h) 내 인덱싱된 조합은 `crawl_and_index` 가 자동 스킵.
"""

from __future__ import annotations

import asyncio
import os
import traceback
from typing import Any

import yaml

try:
    from Tools.crawl_and_index import crawl_and_index
except ImportError:
    from crawl_and_index import crawl_and_index


_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_YAML_PATH = os.path.join(_BACKEND_DIR, "warmup_keywords.yaml")


def _load_yaml(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        return {}
    return data


async def warmup(yaml_path: str | None = None) -> None:
    """YAML 의 keyword × price_band 조합을 순차 크롤한다.

    셀러는 한 번에 전체로 넘겨 `crawl_and_index` 내부 `seller_parallelism` 이 병렬 처리.
    예외가 나도 다음 조합을 계속 진행 — 워밍업은 best-effort.
    """
    path = yaml_path or DEFAULT_YAML_PATH
    config = _load_yaml(path)
    keywords: list[str] = list(config.get("keywords") or [])
    sellers: list[str] = list(config.get("sellers") or [])
    price_bands: list[list[int]] = list(config.get("price_bands") or [])

    if not (keywords and sellers and price_bands):
        print(f"[warmup] 설정이 비어 있음 — 스킵 (path={path})")
        return

    print(
        f"[warmup] 시작 — keywords={len(keywords)}, sellers={len(sellers)}, "
        f"bands={len(price_bands)} → 총 {len(keywords) * len(price_bands)}개 조합"
    )

    for keyword in keywords:
        for band in price_bands:
            if not (isinstance(band, list) and len(band) == 2):
                continue
            min_price, max_price = int(band[0]), int(band[1])
            try:
                result = await crawl_and_index.ainvoke(
                    {
                        "sellers": sellers,
                        "product_keyword": keyword,
                        "min_price": min_price,
                        "max_price": max_price,
                    }
                )
                print(
                    f"[warmup] {keyword} {min_price}~{max_price} → {result[:120]}"
                )
            except Exception as exc:
                print(f"[warmup] 실패: {keyword} {min_price}~{max_price} — {exc}")
                traceback.print_exc()

    print("[warmup] 완료")


if __name__ == "__main__":
    asyncio.run(warmup())
