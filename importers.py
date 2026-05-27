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
            from scrapers_usa.illinois import IllinoisResultsHubScraper
            from services.scraper_deps import ensure_scraper_deps

            ensure_scraper_deps()
            return IllinoisResultsHubScraper().test_connection()
        return {"ok": False, "message": "Fuente no configurada"}

    def import_all(self, days_back=60, max_pages=5):
        if self.source_key == "conectate_rd":
            from scrapers.conectate_rd import import_conectate_rd
            return import_conectate_rd(days_back=days_back)
        if self.source_key == "illinois_lottery":
            from scrapers_usa.illinois import import_illinois_results_hub
            return import_illinois_results_hub()
        return {"ok": False, "message": "Fuente no configurada para importación automática"}

    def parse_and_import(self, lottery_id=None, draw_name=None, html_content=None):
        return self.import_all()


def _illinois_response_with_db_fallback(lottery_id, scrape: dict) -> dict:
    """Si el hub falla pero hay datos en BD, no romper la UI."""
    from models import count_results_for_lottery, get_max_draw_date

    saved_count = count_results_for_lottery(lottery_id)
    latest_date = get_max_draw_date(lottery_id)
    base = {
        "lottery_id": lottery_id,
        "saved_count": saved_count,
        "latest_date": latest_date,
        "hub_url": scrape.get("hub_url"),
        "status_code": scrape.get("status_code"),
        "from_cache": scrape.get("from_cache", False),
        "used_db_fallback": False,
    }

    if scrape.get("ok"):
        return base

    if saved_count > 0:
        return {
            **base,
            "ok": True,
            "status": "cached_fallback",
            "used_db_fallback": True,
            "message": (
                "⚠️ No se pudo actualizar ahora, pero se muestran resultados guardados."
            ),
            "imported": 0,
            "updated": 0,
            "errors": scrape.get("errors", [scrape.get("message")]),
        }

    return {
        **base,
        "ok": False,
        "status": scrape.get("status", "error"),
        "message": scrape.get(
            "message",
            "⚠️ Illinois Results Hub no respondió. Mostrando últimos resultados guardados.",
        ),
        "errors": scrape.get("errors", []),
    }


def refresh_lottery_results_now(
    country,
    state=None,
    lottery=None,
    days=30,
    refresh_all_usa=False,
):
    """Delegado a actualizar_resultados_usa / actualizar_resultados_rd (sin mezclar países)."""
    from services.actualizar_resultados import (
        actualizar_resultados_rd,
        actualizar_resultados_usa,
        es_pais_do,
        es_pais_us,
    )

    if not country or not lottery:
        return {
            "ok": False,
            "status": "error",
            "message": "country y lottery son requeridos",
        }

    if es_pais_us(country):
        return actualizar_resultados_usa(
            lottery,
            state=state or "Illinois",
            days=days,
            refresh_all=bool(refresh_all_usa),
        )

    if es_pais_do(country):
        return actualizar_resultados_rd(lottery, days=days, refresh_all=False)

    return {
        "ok": False,
        "status": "error",
        "message": f"País no soportado: {country}",
    }


def refresh_all_rd_now(days=30):
    """Actualiza historial RD completo (Conectate + LEIDSA). Sin Illinois."""
    from services.actualizar_resultados import actualizar_resultados_rd

    return actualizar_resultados_rd(None, days=days, refresh_all=True)


def refresh_all_usa_illinois_now():
    """Actualiza todos los juegos Illinois. Sin LEIDSA."""
    from services.actualizar_resultados import actualizar_resultados_usa

    return actualizar_resultados_usa(None, refresh_all=True)


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
