"""
web_search_cache.py
===================
Exa/Tavily 등 외부 웹검색 도구 결과를 2단계(L1 in-process LRU + L2 디스크 JSON)로
캐시한다. product_search / seller_search 가 동일 쿼리에 대해 매번 풀 라운드트립을
돌지 않도록 함.

- L1: OrderedDict(max 256) — 동일 프로세스 내 즉시 히트.
- L2: `.chroma_store/web_search_cache.json` — 서버 재시작·멀티워커 간 공유.
- 키: sha1(tool_name + "|" + query.lower().strip())
- TTL: 호출자가 지정. product 6h, seller 24h 권장.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CHROMA_PERSIST_DIR = os.path.abspath(
    os.getenv("CHROMA_PERSIST_DIR", os.path.join(_BACKEND_DIR, ".chroma_store"))
)
_CACHE_PATH = os.path.join(CHROMA_PERSIST_DIR, "web_search_cache.json")
_L1_MAX = 256
_L1: "OrderedDict[str, tuple[str, datetime]]" = OrderedDict()
_L1_LOCK = threading.Lock()
_DISK_LOCK = threading.Lock()


def _cache_key(tool_name: str, query: str) -> str:
    raw = f"{tool_name}|{(query or '').strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_disk() -> dict[str, dict[str, Any]]:
    if not os.path.exists(_CACHE_PATH):
        return {}
    try:
        with open(_CACHE_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_disk(data: dict[str, dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".web_search_cache_", suffix=".json", dir=os.path.dirname(_CACHE_PATH)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, ensure_ascii=False)
        os.replace(tmp_path, _CACHE_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _l1_get(key: str) -> str | None:
    with _L1_LOCK:
        entry = _L1.get(key)
        if entry is None:
            return None
        result, expires_at = entry
        if _now() >= expires_at:
            _L1.pop(key, None)
            return None
        _L1.move_to_end(key)
        return result


def _l1_set(key: str, result: str, expires_at: datetime) -> None:
    with _L1_LOCK:
        _L1[key] = (result, expires_at)
        _L1.move_to_end(key)
        while len(_L1) > _L1_MAX:
            _L1.popitem(last=False)


def _disk_get(key: str) -> tuple[str, datetime] | None:
    with _DISK_LOCK:
        data = _load_disk()
    entry = data.get(key)
    if entry is None:
        return None
    expires_raw = entry.get("expires_at")
    result = entry.get("result")
    if not isinstance(result, str) or not expires_raw:
        return None
    expires_at = _parse_safe(expires_raw)
    if expires_at is None:
        return None
    if _now() >= expires_at:
        return None
    return result, expires_at


def _disk_set(key: str, result: str, expires_at: datetime) -> None:
    with _DISK_LOCK:
        data = _load_disk()
        # 만료된 다른 엔트리 청소 — 파일 크기 무한 증가 방지
        now = _now()
        data = {
            k: v
            for k, v in data.items()
            if isinstance(v, dict)
            and v.get("expires_at")
            and (parsed_expiry := _parse_safe(v["expires_at"])) is not None
            and parsed_expiry > now
        }
        data[key] = {"result": result, "expires_at": expires_at.isoformat()}
        _save_disk(data)


def _parse_safe(raw: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def cached_web_search(
    tool_name: str,
    query: str,
    ttl_seconds: int,
    fetch_fn: Callable[[], Awaitable[Any]],
) -> str:
    """tool_name + query 로 캐시 조회 → 미스 시 fetch_fn 으로 실시간 호출 후 저장.

    fetch_fn 결과가 str 이 아니면 json.dumps 로 직렬화해 보존한다 (Exa raw dict 대응).
    """
    key = _cache_key(tool_name, query)

    cached = _l1_get(key)
    if cached is not None:
        return cached

    disk_hit = _disk_get(key)
    if disk_hit is not None:
        result, expires_at = disk_hit
        _l1_set(key, result, expires_at)
        return result

    # 동시 요청이 같은 키를 동시에 fetch할 수 있지만 결과 동일 → 마지막 쓰기가 이긴다.
    # 멀티 이벤트루프(ProactorEventLoop 격리 스레드) 호환을 위해 asyncio.Lock 은 쓰지 않음.
    raw = await fetch_fn()
    result = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    expires_at = _now() + timedelta(seconds=ttl_seconds)
    _l1_set(key, result, expires_at)
    _disk_set(key, result, expires_at)
    return result


def cache_path() -> str:
    """디버그/테스트용 — 현재 사용 중인 JSON 경로 노출."""
    return _CACHE_PATH


def clear_cache() -> None:
    """테스트 헬퍼: L1 + 디스크 모두 비움."""
    with _L1_LOCK:
        _L1.clear()
    with _DISK_LOCK:
        if os.path.exists(_CACHE_PATH):
            os.remove(_CACHE_PATH)
