"""Debug de fuentes RD y resultados en DB."""
from __future__ import annotations

from models import (
    count_results_by_lottery,
    get_all_lotteries,
    get_max_draw_date,
    get_recent_results_rows,
    get_results,
)
from services.lottery_normalize import normalize_lottery_name
from services.rd_lottery_config import LOTTERY_CONFIG, get_rd_lottery_config

_SOURCE_ERRORS: dict[str, str] = {}


def record_source_error(source: str, message: str) -> None:
    if source and message:
        _SOURCE_ERRORS[source] = message


def debug_lottery_source(source_key: str) -> dict:
    """GET /debug/lottery/<source>"""
    source_key = (source_key or "").strip().lower().replace("-", "_")
    cfg = None
    label = None
    for lot_label, lot_cfg in LOTTERY_CONFIG.items():
        if lot_cfg.get("source", "").replace("-", "_") == source_key:
            cfg = lot_cfg
            label = lot_label
            break
        if normalize_lottery_name(lot_label) == source_key:
            cfg = lot_cfg
            label = lot_label
            break
    if not cfg:
        cfg = get_rd_lottery_config(source_key)
        label = source_key

    scraper_exists = False
    if cfg:
        src = cfg.get("source", "")
        scraper_exists = src in ("conectate", "leidsa", "leidsa_game")
        if src == "conectate":
            scraper_exists = bool(cfg.get("conectate_pages") or cfg.get("anguila"))

    lotteries = get_all_lotteries(active_only=False)
    db_rows = []
    last_results = []
    for name in (cfg or {}).get("db_names", [label or source_key]):
        lot = next(
            (l for l in lotteries if normalize_lottery_name(l["name"]) == normalize_lottery_name(name)),
            None,
        )
        if not lot:
            continue
        db_rows.append(lot)
        last_results.extend(get_results(lot["id"], limit=5))

    return {
        "ok": bool(cfg),
        "source": source_key,
        "label": label,
        "scraper_exists": scraper_exists,
        "draws_configured": (cfg or {}).get("draws", []),
        "enabled": (cfg or {}).get("enabled", False),
        "last_results_in_db": last_results,
        "last_error": _SOURCE_ERRORS.get(source_key),
        "normalized_names": {
            "source_key": source_key,
            "db_names": (cfg or {}).get("db_names", []),
            "variants": [normalize_lottery_name(n) for n in (cfg or {}).get("db_names", [])],
        },
        "db_lotteries": db_rows,
        "max_draw_date": get_max_draw_date(db_rows[0]["id"]) if db_rows else None,
    }


def debug_resultados_general() -> dict:
    """GET /debug/resultados"""
    by_lottery = count_results_by_lottery()
    total = sum(int(r.get("total") or 0) for r in by_lottery)
    by_date: dict[str, int] = {}
    recent = get_recent_results_rows(20)
    for row in recent:
        d = row.get("draw_date") or ""
        by_date[d] = by_date.get(d, 0) + 1
    return {
        "ok": True,
        "total_results_db": total,
        "by_lottery": by_lottery,
        "by_date_recent": dict(sorted(by_date.items(), reverse=True)),
        "last_20_rows": recent,
    }
