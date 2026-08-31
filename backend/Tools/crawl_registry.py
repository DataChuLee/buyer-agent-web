"""
crawl_registry.py
=================
크롤·인덱싱 이력 영속 레지스트리.

`crawl_and_index` 가 동일 (sellers, keyword, min_price, max_price) 조합에 대해
재크롤을 건너뛰도록 in-process set 대신 디스크 JSON 파일로 상태를 보존한다.

- 저장 경로: `CHROMA_PERSIST_DIR/crawl_registry.json` (기본 `backend/.chroma_store`)
- TTL: 기본 24h. 만료 시 자동으로 재크롤 허용 (가격·재고 변동 반영).
- threading.Lock + atomic replace 로 멀티스레드/멀티워커 safe.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHROMA_PERSIST_DIR = os.path.abspath(
    os.getenv("CHROMA_PERSIST_DIR", os.path.join(_BACKEND_DIR, ".chroma_store"))
)
_REGISTRY_PATH = os.path.join(CHROMA_PERSIST_DIR, "crawl_registry.json")
_DEFAULT_TTL = timedelta(hours=24)
_LOCK = threading.Lock()


def _registry_key(sellers: list[str], keyword: str, min_price: int, max_price: int) -> str:
    sellers_sorted = ",".join(sorted(s.strip() for s in sellers if s.strip()))
    return f"{sellers_sorted}|{keyword}|{min_price}|{max_price}"


def _load_registry() -> dict[str, dict[str, Any]]:
    if not os.path.exists(_REGISTRY_PATH):
        return {}
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_registry(data: dict[str, dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
    # atomic write: tmp 파일에 쓴 뒤 os.replace
    fd, tmp_path = tempfile.mkstemp(
        prefix=".crawl_registry_", suffix=".json", dir=os.path.dirname(_REGISTRY_PATH)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _REGISTRY_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _is_expired(entry: dict[str, Any], ttl: timedelta = _DEFAULT_TTL) -> bool:
    indexed_at_raw = entry.get("indexed_at")
    if not indexed_at_raw:
        return True
    try:
        indexed_at = datetime.fromisoformat(str(indexed_at_raw))
    except (TypeError, ValueError):
        return True
    if indexed_at.tzinfo is None:
        indexed_at = indexed_at.replace(tzinfo=timezone.utc)
    else:
        indexed_at = indexed_at.astimezone(timezone.utc)
    return datetime.now(timezone.utc) - indexed_at > ttl


def is_already_indexed(
    sellers: list[str], keyword: str, min_price: int, max_price: int
) -> bool:
    """동일 조건으로 크롤·인덱싱된 적이 있고, TTL 내 유효한지 확인.

    1) 정확 키 매칭 우선.
    2) 미스 시 fuzzy fallback — 워밍업이 더 넓은 범위를 인덱싱했고 사용자 요청이
       그 부분집합인 경우 hit 처리. ChromaDB metadata filter 가 셀러·가격대를
       다시 거르므로 결과 정합성은 유지된다.
        - 요청 셀러 ⊆ 등록 셀러
        - 등록 키워드가 요청 키워드의 substring (예: "나이키 머큐리얼" ⊆ "나이키 머큐리얼 베이퍼")
        - 요청 가격대 ⊆ 등록 가격대
    """
    key = _registry_key(sellers, keyword, min_price, max_price)
    with _LOCK:
        registry = _load_registry()

    entry = registry.get(key)
    if entry is not None and not _is_expired(entry):
        return True

    requested_sellers = {s.strip() for s in sellers if s.strip()}
    keyword_lower = (keyword or "").lower()
    if not requested_sellers or not keyword_lower:
        return False

    for candidate in registry.values():
        if not isinstance(candidate, dict):
            continue
        if _is_expired(candidate):
            continue
        entry_sellers = {s.strip() for s in (candidate.get("sellers") or [])}
        if not requested_sellers.issubset(entry_sellers):
            continue
        entry_keyword = str(candidate.get("keyword") or "").lower()
        if not entry_keyword or entry_keyword not in keyword_lower:
            continue
        try:
            entry_min = int(candidate.get("min_price", 0))
            entry_max = int(candidate.get("max_price", 0))
        except (TypeError, ValueError):
            continue
        if min_price >= entry_min and max_price <= entry_max:
            return True
    return False


def register_crawl(
    sellers: list[str],
    keyword: str,
    min_price: int,
    max_price: int,
    item_count: int = 0,
) -> None:
    """크롤 성공 후 레지스트리에 기록 (TTL 24h)."""
    key = _registry_key(sellers, keyword, min_price, max_price)
    entry = {
        "sellers": sorted(s.strip() for s in sellers if s.strip()),
        "keyword": keyword,
        "min_price": min_price,
        "max_price": max_price,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "item_count": item_count,
    }
    with _LOCK:
        registry = _load_registry()
        registry[key] = entry
        _save_registry(registry)


def registry_path() -> str:
    """디버그/테스트용 — 현재 사용 중인 JSON 경로 노출."""
    return _REGISTRY_PATH
