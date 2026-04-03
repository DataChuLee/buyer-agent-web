import re


SELLER_CANONICALS = {
    "crazy11": {
        "display": "크레이지11",
        "crawler": "crazy11",
        "aliases": ("crazy11", "crazy 11", "크레이지11", "크레이지 11"),
    },
    "soccerboom": {
        "display": "사커붐",
        "crawler": "soccerboom",
        "aliases": ("soccerboom", "soccer boom", "사커붐"),
    },
    "redsoccer": {
        "display": "레드사커",
        "crawler": "redsoccer",
        "aliases": ("redsoccer", "red soccer", "레드사커"),
    },
    "cafostore": {
        "display": "카포스토어",
        "crawler": "cafostore",
        "aliases": ("cafostore", "cafo store", "카포스토어"),
    },
}


def _normalize_lookup_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


_SELLER_ALIAS_LOOKUP: dict[str, dict[str, str | tuple[str, ...]]] = {}
for canonical in SELLER_CANONICALS.values():
    for alias in canonical["aliases"]:
        _SELLER_ALIAS_LOOKUP[_normalize_lookup_key(alias)] = canonical


def _build_alias_pattern(alias: str) -> str:
    tokens = alias.split()
    if len(tokens) <= 1:
        return re.escape(alias)
    return r"\s*".join(re.escape(token) for token in tokens)


def normalize_seller_display(value: str) -> str:
    canonical = _SELLER_ALIAS_LOOKUP.get(_normalize_lookup_key(value))
    return canonical["display"] if canonical else str(value or "").strip()


def normalize_seller_crawler(value: str) -> str:
    canonical = _SELLER_ALIAS_LOOKUP.get(_normalize_lookup_key(value))
    return canonical["crawler"] if canonical else str(value or "").strip()


def replace_seller_aliases_in_query(query: str) -> str:
    normalized = str(query or "")
    for canonical in SELLER_CANONICALS.values():
        display = canonical["display"]
        aliases = sorted(set(canonical["aliases"]), key=len, reverse=True)
        for alias in aliases:
            if alias == display:
                continue
            normalized = re.sub(
                _build_alias_pattern(alias),
                display,
                normalized,
                flags=re.IGNORECASE,
            )
    return normalized


def find_seller_displays_in_query(query: str) -> list[str]:
    found: list[str] = []
    normalized_query = str(query or "")

    for canonical in SELLER_CANONICALS.values():
        display = canonical["display"]
        for alias in canonical["aliases"]:
            if re.search(_build_alias_pattern(alias), normalized_query, flags=re.IGNORECASE):
                if display not in found:
                    found.append(display)
                break

    return found
