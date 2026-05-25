import csv
import io
import json
from datetime import datetime

import requests

from models import (
    create_result,
    get_all_lotteries,
    get_api_configs,
    get_db,
    parse_numbers,
    format_numbers,
)


CSV_COLUMNS = [
    "country", "state", "lottery_name", "draw_name", "draw_time",
    "draw_date", "numbers", "bonus_number", "fireball_number", "source_url",
]


def _find_lottery(lotteries, country, state, lottery_name):
    state = (state or "").strip()
    country_up = country.upper()
    name_up = lottery_name.upper()
    for lot in lotteries:
        if lot["country"].upper() != country_up or lot["name"].upper() != name_up:
            continue
        if country_up == "RD" and not state:
            return lot
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

            if not all([country, lottery_name, draw_name, draw_date, numbers]):
                errors.append(f"Fila {row_num}: campos obligatorios incompletos")
                continue

            lottery = _find_lottery(lotteries, country, state, lottery_name)
            if not lottery:
                errors.append(f"Fila {row_num}: lotería '{lottery_name}' no encontrada")
                continue

            create_result(
                lottery["id"], draw_name, draw_time, draw_date, numbers,
                bonus, fireball, source_url, confirmed=1,
            )
            imported += 1
        except Exception as e:
            errors.append(f"Fila {row_num}: {str(e)}")

    return {"imported": imported, "errors": errors}


def import_manual(data):
    lottery_id = data.get("lottery_id")
    draw_name = data.get("draw_name", "").strip()
    draw_time = data.get("draw_time", "").strip()
    draw_date = data.get("draw_date", "").strip()
    numbers = data.get("numbers", "").strip()
    bonus = data.get("bonus_number", "").strip() or None
    fireball = data.get("fireball_number", "").strip() or None
    source_url = data.get("source_url", "").strip() or None
    confirmed = 1 if data.get("confirmed") else 0

    if not all([lottery_id, draw_name, draw_date, numbers]):
        return {"ok": False, "message": "Campos obligatorios incompletos"}

    result_id = create_result(
        lottery_id, draw_name, draw_time, draw_date, numbers,
        bonus, fireball, source_url, confirmed,
    )
    return {"ok": True, "result_id": result_id}


class ExternalAPIConnector:
    """Conector preparado para APIs externas con API KEY."""

    def __init__(self, source_name, api_url, api_key):
        self.source_name = source_name
        self.api_url = api_url
        self.api_key = api_key

    def fetch_results(self, lottery_name=None, date_from=None):
        if not self.api_url or not self.api_key:
            return {
                "ok": False,
                "message": "API no configurada. Configure api_url y api_key en el panel admin.",
            }

        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        params = {}
        if lottery_name:
            params["lottery"] = lottery_name
        if date_from:
            params["date_from"] = date_from

        try:
            resp = requests.get(self.api_url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return {"ok": True, "data": data, "source": self.source_name}
        except requests.RequestException as e:
            return {"ok": False, "message": f"Error al conectar con API: {str(e)}"}

    def import_results(self, lottery_id, draw_name, api_data):
        imported = 0
        items = api_data if isinstance(api_data, list) else api_data.get("results", [])
        for item in items:
            numbers = item.get("numbers") or item.get("winning_numbers")
            if not numbers:
                continue
            if isinstance(numbers, list):
                numbers = format_numbers(numbers)
            create_result(
                lottery_id,
                item.get("draw_name", draw_name),
                item.get("draw_time", ""),
                item.get("draw_date", item.get("date", "")),
                numbers,
                item.get("bonus_number"),
                item.get("fireball_number"),
                item.get("source_url", self.api_url),
                confirmed=0,
            )
            imported += 1
        return imported


class WebScraperImporter:
    """Importador para páginas oficiales: Conectate RD e Illinois Lottery."""

    SOURCES = {
        "illinois_lottery": "https://www.illinoislottery.com/results-hub",
        "conectate_rd": "https://www.conectate.com.do/",
    }

    def __init__(self, source_key):
        self.source_key = source_key
        self.base_url = self.SOURCES.get(source_key, "")

    def fetch_page(self, path=""):
        if self.source_key == "conectate_rd":
            from scrapers.conectate_rd import ConectateRDScraper
            return ConectateRDScraper().fetch_page(path)
        if self.source_key == "illinois_lottery":
            from services.resultados.illinois_scraper import IllinoisResultsHubScraper
            return IllinoisResultsHubScraper().fetch_results_hub()
        if not self.base_url:
            return {"ok": False, "message": "Fuente no configurada"}
        url = self.base_url.rstrip("/") + "/" + path.lstrip("/")
        try:
            resp = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "LotteryAnalyzer/1.0 (statistical analysis tool)"},
            )
            resp.raise_for_status()
            return {"ok": True, "html": resp.text, "url": url}
        except requests.RequestException as e:
            return {"ok": False, "message": f"Error al obtener página: {str(e)}"}

    def test_connection(self):
        if self.source_key == "conectate_rd":
            page = self.fetch_page("/loterias/")
            if page.get("ok"):
                return {
                    "ok": True,
                    "message": "Conexión exitosa con Conectate.com.do (RD).",
                    "url": page["url"],
                }
            return page
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


def refresh_lottery_results_now(country, state=None, lottery=None):
    """Ejecuta scraper según país y devuelve fecha más nueva."""
    from models import get_max_draw_date

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

    try:
        if country_up == "RD":
            lot_type = (lot.get("type") or "").lower()
            if lot_type.startswith("leidsa_") or lot["name"].lower() == "leidsa":
                from services.leidsa_service import update_leidsa_now
                scrape = update_leidsa_now()
            else:
                from scrapers.conectate_rd import import_conectate_lottery_today
                scrape = import_conectate_lottery_today(lot["name"])
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
        return {
            "ok": False,
            "status": "error",
            "message": f"Error al ejecutar scraper: {e}",
        }

    if not scrape.get("ok"):
        return {
            "ok": False,
            "status": "error",
            "message": scrape.get("message", "Error al importar resultados."),
        }

    latest_date = get_max_draw_date(lottery_id)
    imported = scrape.get("imported", 0)
    updated = scrape.get("updated", 0)

    if imported + updated == 0:
        return {
            "ok": True,
            "status": "no_new",
            "message": "No hay resultados nuevos todavía",
            "latest_date": latest_date,
            "imported": imported,
            "updated": updated,
            "lottery_id": lottery_id,
        }

    return {
        "ok": True,
        "status": "updated",
        "message": "Resultados actualizados",
        "latest_date": latest_date,
        "imported": imported,
        "updated": updated,
        "lottery_id": lottery_id,
    }


def refresh_all_rd_now():
    """Actualiza LEIDSA (leidsa.com) + demás loterías RD (Conectate). LEIDSA puede fallar sin romper el resto."""
    from services.leidsa_service import update_leidsa_now

    leidsa_result = update_leidsa_now()
    details = [{"name": "LEIDSA", **leidsa_result}]
    total_imported = leidsa_result.get("inserted", leidsa_result.get("imported", 0))
    total_updated = leidsa_result.get("updated", 0)
    errors = []
    leidsa_ok = bool(leidsa_result.get("ok"))

    if not leidsa_ok:
        errors.append(
            leidsa_result.get("message")
            or "LEIDSA: error temporal — otras loterías RD continúan."
        )

    from scrapers.conectate_rd import import_conectate_lottery_today

    for lot in get_all_lotteries(active_only=True):
        if lot.get("country") != "RD":
            continue
        ltype = (lot.get("type") or "").lower()
        if ltype.startswith("leidsa_") or lot["name"].lower() == "leidsa":
            continue
        try:
            scrape = import_conectate_lottery_today(lot["name"])
            details.append({"name": lot["name"], **scrape})
            if scrape.get("ok"):
                total_imported += scrape.get("imported", 0)
                total_updated += scrape.get("updated", 0)
            else:
                errors.append(f"{lot['name']}: {scrape.get('message', 'error')}")
        except Exception as exc:
            errors.append(f"{lot['name']}: {exc}")

    other_ok = any(
        d.get("ok") and d.get("name") != "LEIDSA"
        for d in details
    ) or total_imported + total_updated > 0

    return {
        "ok": leidsa_ok or other_ok,
        "status": "updated" if total_imported + total_updated else "no_new",
        "message": f"RD: {total_imported} nuevos, {total_updated} actualizados.",
        "imported": total_imported,
        "updated": total_updated,
        "details": details,
        "errors": errors,
        "leidsa_ok": leidsa_ok,
        "leidsa_error": None if leidsa_ok else errors[0] if errors else "LEIDSA falló",
    }


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
