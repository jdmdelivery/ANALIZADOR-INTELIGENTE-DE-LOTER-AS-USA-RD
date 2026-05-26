import csv
import io
import json
from datetime import datetime

import requests

from models import (
    get_all_lotteries,
    get_api_configs,
    get_db,
    upsert_result,
    format_numbers,
)
from services.lottery_normalize import find_lottery_in_list, normalize_lottery_name
from services.rd_lottery_config import get_rd_lottery_config


CSV_COLUMNS = [
    "country", "state", "lottery_name", "draw_name", "draw_time",
    "draw_date", "numbers", "bonus_number", "fireball_number", "source_url",
]


def _find_lottery(lotteries, country, state, lottery_name):
    state = (state or "").strip()
    country_up = country.upper()
    if country_up == "RD" and not state:
        return find_lottery_in_list(lotteries, lottery_name, country="RD")
    name_up = lottery_name.upper()
    for lot in lotteries:
        if lot["country"].upper() != country_up or lot["name"].upper() != name_up:
            continue
        if (lot["state"] or "").upper() == state.upper():
            return lot
    return None


def import_csv(file_content):
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(file_content))
    lotteries = get_all_lotteries()
    imported = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        try:
            country = row.get("country", "").strip()
            state = row.get("state", "").strip()
            lottery_name = row.get("lottery_name", "").strip()
            draw_name = row.get("draw_name", "").strip()
            draw_time = row.get("draw_time", "").strip()
            draw_date = row.get("draw_date", "").strip()
            numbers = row.get("numbers", "").strip()
            bonus = row.get("bonus_number", "").strip() or None
            fireball = row.get("fireball_number", "").strip() or None
            source_url = row.get("source_url", "").strip() or None

            lottery = _find_lottery(lotteries, country, state, lottery_name)
            if not lottery:
                errors.append(f"Fila {row_num}: lotería '{lottery_name}' no encontrada")
                continue

            upsert_result(
                lottery["id"], draw_name, draw_time, draw_date, numbers,
                bonus_number=bonus, fireball_number=fireball, source_url=source_url,
                confirmed=1, fuente="csv_import", estado="publicado",
            )
            imported += 1
        except Exception as e:
            errors.append(f"Fila {row_num}: {e}")

    return {
        "ok": True,
        "imported": imported,
        "errors": errors,
        "message": f"CSV: {imported} resultados importados.",
    }


class ExternalAPIConnector:
    def __init__(self, source_name, api_url, api_key):
        self.source_name = source_name
        self.api_url = api_url
        self.api_key = api_key

    def fetch_results(self):
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.get(self.api_url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "data": data}
        except Exception as e:
            return {"ok": False, "message": str(e)}


class WebScraperImporter:
    def __init__(self, source_key):
        self.source_key = source_key

    def test_connection(self):
        if self.source_key == "conectate_rd":
            from scrapers.conectate_rd import ConectateRDScraper
            scraper = ConectateRDScraper()
            page = scraper.fetch_page("/loterias/")
            if page.get("ok"):
                return {"ok": True, "message": "Conexión exitosa con Conectate RD."}
            return {"ok": False, "message": page.get("message", "Error de conexión")}
        if self.source_key == "illinois_lottery":
            from services.resultados.illinois_scraper import IllinoisResultsHubScraper
            return IllinoisResultsHubScraper().test_connection()
        return {"ok": False, "message": "Fuente no configurada"}

    def import_all(self, days_back=60, max_pages=5):
        if self.source_key == "conectate_rd":
            from scrapers.conectate_rd import import_conectate_rd
            return import_conectate_rd(days_back=days_back)
        if self.source_key == "illinois_lottery":
            from services.resultados.illinois_scraper import import_illinois_results_hub
            return import_illinois_results_hub()
        return {"ok": False, "message": "Fuente no configurada para importación automática"}

    def parse_and_import(self, lottery_id=None, draw_name=None, html_content=None):
        return self.import_all()


def refresh_lottery_results_now(country, state=None, lottery=None, days=30):
    """Descarga historial de la lotería seleccionada (RD: 30 días por defecto)."""
    from models import get_max_draw_date
    from services.history_fetch import fetch_history_for_source

    if not country or not lottery:
        return {
            "ok": False,
            "status": "error",
            "message": "country y lottery son requeridos",
        }

    lotteries = get_all_lotteries()
    lot = _find_lottery(lotteries, country, state or "", lottery)
    if not lot:
        return {
            "ok": False,
            "status": "error",
            "message": f"Lotería '{lottery}' no encontrada.",
        }

    lottery_id = lot["id"]
    country_up = country.upper()
    state_up = (state or "").strip()
    days = int(days or 30)

    try:
        if country_up == "RD":
            lot_type = (lot.get("type") or "").lower()
            cfg = get_rd_lottery_config(lot["name"])
            if lot_type.startswith("leidsa_"):
                from services.leidsa_config import LEIDSA_HISTORY_GAMES
                from services.leidsa_history import fetch_leidsa_game_history, save_leidsa_rows

                game = next((g for g in LEIDSA_HISTORY_GAMES if g.get("slug") == lot_type), None)
                if not game:
                    scrape = fetch_history_for_source("leidsa", days=days)
                else:
                    res = fetch_leidsa_game_history(game, days=days, limit=120)
                    rows = res.get("rows") or []
                    batch = save_leidsa_rows(rows) if rows else {"inserted": 0, "updated": 0}
                    scrape = {
                        "ok": bool(rows),
                        "imported": batch.get("inserted", 0),
                        "updated": batch.get("updated", 0),
                        "message": (
                            f"{lot['name']}: {days} días, {len(rows)} sorteos, "
                            f"{batch.get('inserted', 0)} nuevos."
                        ),
                    }
            elif cfg and cfg.get("source") == "leidsa":
                scrape = fetch_history_for_source("leidsa", days=days)
            else:
                from services.new_lotteries import is_new_rd_lottery

                if is_new_rd_lottery(lot):
                    from scrapers.conectate_rd import import_conectate_lottery_bulk_style

                    scrape = import_conectate_lottery_bulk_style(lot["name"], days_back=days)
                else:
                    scrape = fetch_history_for_source(
                        "conectate", days=days, lottery_name=lot["name"]
                    )
        elif country_up == "USA" and state_up.lower() == "illinois":
            from services.resultados.illinois_scraper import import_illinois_lottery_now
            scrape = import_illinois_lottery_now(lot["name"])
        else:
            return {
                "ok": False,
                "status": "error",
                "message": "Scraper no disponible para esta lotería.",
            }
    except Exception as e:
        from services.rd_debug import record_source_error
        cfg = get_rd_lottery_config(lot.get("name", ""))
        src = (cfg or {}).get("source", "rd")
        record_source_error(src, str(e))
        return {
            "ok": False,
            "status": "error",
            "message": f"Error temporal en {lot.get('name', lottery)}: {e}",
        }

    if not scrape.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "message": scrape.get("message", "Error al importar resultados."),
        }

    latest_date = get_max_draw_date(lottery_id)
    imported = scrape.get("imported", scrape.get("inserted", 0))
    updated = scrape.get("updated", 0)
    saved = imported + updated

    if saved == 0:
        return {
            "ok": True,
            "status": "no_new",
            "message": scrape.get("message") or "No hay resultados nuevos en el rango",
            "latest_date": latest_date,
            "imported": imported,
            "updated": updated,
            "days": days,
            "lottery_id": lottery_id,
        }

    return {
        "ok": True,
        "status": "updated",
        "message": scrape.get("message") or f"Historial actualizado ({days} días).",
        "latest_date": latest_date,
        "imported": imported,
        "updated": updated,
        "days": days,
        "lottery_id": lottery_id,
    }


def refresh_all_rd_now(days=30):
    """Actualiza historial RD completo (Conectate + LEIDSA)."""
    from services.history_fetch import fetch_all_rd_history
    return fetch_all_rd_history(days=int(days or 30))


def import_manual(form):
    """Agrega un resultado manual desde el panel admin."""
    try:
        lottery_id = int(form.get("lottery_id") or 0)
        draw_name = (form.get("draw_name") or "").strip()
        draw_time = (form.get("draw_time") or "").strip()
        draw_date = (form.get("draw_date") or "").strip()
        numbers = (form.get("numbers") or "").strip()
        if not lottery_id or not draw_name or not draw_date or not numbers:
            return {"ok": False, "message": "Campos requeridos incompletos."}
        upsert_result(
            lottery_id,
            draw_name,
            draw_time,
            draw_date,
            numbers,
            bonus_number=form.get("bonus_number") or None,
            fireball_number=form.get("fireball_number") or None,
            source_url=form.get("source_url") or None,
            confirmed=1,
            fuente="manual",
            estado="publicado",
        )
        return {"ok": True, "message": "Resultado agregado."}
    except Exception as e:
        return {"ok": False, "message": str(e)}


def sync_from_api(source_name):
    configs = get_api_configs()
    config = next((c for c in configs if c["source_name"] == source_name), None)
    if not config:
        return {"ok": False, "message": f"Fuente API '{source_name}' no configurada"}

    with get_db() as conn:
        row = conn.execute(
            "SELECT api_url, api_key FROM api_config WHERE source_name = ?",
            (source_name,),
        ).fetchone()
        if not row:
            return {"ok": False, "message": "Configuración API no encontrada"}

    connector = ExternalAPIConnector(source_name, row["api_url"], row["api_key"])
    result = connector.fetch_results()
    if result.get("ok"):
        with get_db() as conn:
            conn.execute(
                "UPDATE api_config SET last_sync = ? WHERE source_name = ?",
                (datetime.now().isoformat(), source_name),
            )
    return result
