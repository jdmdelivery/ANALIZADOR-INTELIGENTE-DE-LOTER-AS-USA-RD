"""Diagnóstico de fuentes RD (solo lectura, no escribe en BD)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scrapers.kiskoo_nuxt_parser import (
    CONECTATE_API,
    CONECTATE_PAYLOAD,
    LD_API,
    LD_PAYLOAD,
    fetch_hub_rows,
)
from scrapers.rd_http import fetch_rd_json, fetch_rd_url
from services.leidsa_config import SOURCE_URL as LEIDSA_URL


def _print_row(row: dict) -> None:
    print(f"SOURCE: {row.get('source')}")
    print(f"URL: {row.get('url')}")
    print(f"STATUS: {row.get('status')}")
    print(f"CONTENT-TYPE: {row.get('content_type')}")
    print(f"BYTES: {row.get('bytes')}")
    print(f"LATENCY: {row.get('latency_ms')}")
    print(f"ROWS: {row.get('rows')}")
    print(f"LATEST: {row.get('latest')}")
    print(f"ERROR: {row.get('error')}")
    print("-" * 60)


def probe_conectate() -> dict:
    t0 = time.monotonic()
    payload = fetch_rd_json(CONECTATE_PAYLOAD, source="diag_conectate_payload", timeout=15)
    hub = fetch_hub_rows(api_base=CONECTATE_API, payload_url=CONECTATE_PAYLOAD, days=30, source_label="diag_conectate", force_refresh=True)
    rows = hub.get("rows") or []
    latest = max((r.get("draw_date") for r in rows if r.get("draw_date")), default=None)
    return {
        "source": "conectate",
        "url": hub.get("url") or CONECTATE_API,
        "status": hub.get("status_code") or payload.get("status_code"),
        "content_type": payload.get("content_type", ""),
        "bytes": payload.get("bytes", 0),
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "rows": len(rows),
        "latest": latest,
        "error": hub.get("error") or payload.get("error"),
    }


def probe_ld() -> dict:
    t0 = time.monotonic()
    payload = fetch_rd_json(LD_PAYLOAD, source="diag_ld_payload", timeout=15)
    hub = fetch_hub_rows(api_base=LD_API, payload_url=LD_PAYLOAD, days=30, source_label="diag_ld", force_refresh=True)
    rows = hub.get("rows") or []
    latest = max((r.get("draw_date") for r in rows if r.get("draw_date")), default=None)
    return {
        "source": "loteriasdominicanas",
        "url": hub.get("url") or LD_API,
        "status": hub.get("status_code") or payload.get("status_code"),
        "content_type": payload.get("content_type", ""),
        "bytes": payload.get("bytes", 0),
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "rows": len(rows),
        "latest": latest,
        "error": hub.get("error") or payload.get("error"),
    }


def probe_leidsa() -> dict:
    t0 = time.monotonic()
    out = fetch_rd_url(LEIDSA_URL, source="diag_leidsa", timeout=20, min_bytes=2000)
    return {
        "source": "leidsa",
        "url": out.get("url") or LEIDSA_URL,
        "status": out.get("status_code"),
        "content_type": out.get("content_type", ""),
        "bytes": out.get("bytes", 0),
        "latency_ms": int((time.monotonic() - t0) * 1000),
        "rows": 0,
        "latest": None,
        "error": out.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="all", choices=["all", "conectate", "ld", "leidsa"])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    probes = []
    if args.source in ("all", "conectate"):
        probes.append(probe_conectate())
    if args.source in ("all", "ld"):
        probes.append(probe_ld())
    if args.source in ("all", "leidsa"):
        probes.append(probe_leidsa())

    for row in probes:
        _print_row(row)
    if args.verbose:
        print(json.dumps(probes, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
