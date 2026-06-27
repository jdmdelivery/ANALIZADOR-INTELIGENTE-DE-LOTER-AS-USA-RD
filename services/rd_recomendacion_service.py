"""
Motor de recomendación RD inteligente — rotación diaria, anti-repetición e historial.
Solo República Dominicana; no afecta predicciones USA.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta

from models import (
    get_lottery,
    get_recent_recomendaciones_rd,
    get_recomendacion_rd_hoy,
    get_results_for_analysis,
    save_recomendacion_rd,
)
from services.rd_fuentes_service import get_fuentes_status, get_last_rd_update
from services.recommendations.draw_resolver import resolve_prediction_draw
from services.recommendations.scoring import confidence_from_score

ALGO_VERSION = "rd_inteligente_v1"
EXPLICACION_BASE = (
    "Estos números fueron seleccionados combinando frecuencia reciente, tendencia de "
    "7/15/30 días, comportamiento por posición, día de semana, ausencia y rotación "
    "anti-repetición. También se revisó que esta combinación no haya sido recomendada "
    "recientemente. Análisis estadístico de referencia — no garantiza ganar."
)
LOW_CONF_MSG = "Confianza baja: usar como referencia, no jugada fuerte."


def _daily_seed(fecha: str, loteria: str, sorteo: str, horario: str) -> int:
    raw = f"{fecha}|{loteria}|{sorteo}|{horario}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:8], 16)


def _combo_key(nums) -> tuple:
    if isinstance(nums, str):
        import json
        try:
            nums = json.loads(nums)
        except (TypeError, ValueError):
            nums = [x for x in nums.replace("[", "").replace("]", "").replace('"', "").split(",") if x.strip()]
    return tuple(str(n).zfill(2) for n in (nums or []))


def _yesterday_draw_numbers(lottery_id: int, draw_name: str) -> set[str]:
    rows = get_results_for_analysis(lottery_id, draw_name, days=3)
    if not rows:
        return set()
    latest_date = rows[0].get("draw_date")
    if not latest_date:
        return set()
    yday = (datetime.strptime(latest_date[:10], "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
    nums: set[str] = set()
    for r in rows:
        if (r.get("draw_date") or "")[:10] == yday:
            for n in r.get("numbers") or []:
                nums.add(str(n).zfill(2))
    return nums


def _build_ranked_pools(base: dict) -> dict[str, list[str]]:
    hot = [str(n).zfill(2) for n in (base.get("hot_numbers") or [])]
    cold = [str(n).zfill(2) for n in (base.get("cold_numbers") or [])]
    top = [p["number"] for p in (base.get("top_numbers") or {}).get("top_50", [])]
    if not top:
        profiles = base.get("number_profiles") or {}
        top = sorted(
            profiles.keys(),
            key=lambda k: -profiles[k].get("score", 0),
        )
    trend = top[5:25] if len(top) > 5 else top
    return {"hot": hot or top[:15], "trend": trend or top, "cold": cold or top[25:40], "all": top}


def _pick_with_pool(
    pools: dict[str, list[str]],
    seed: int,
    *,
    banned: set[str],
    used: set[str],
) -> str | None:
    rng = random.Random(seed)
    segments = [
        ("hot", 0.40),
        ("trend", 0.30),
        ("cold", 0.20),
        ("all", 0.10),
    ]
    roll = rng.random()
    acc = 0.0
    chosen_seg = "all"
    for name, weight in segments:
        acc += weight
        if roll <= acc:
            chosen_seg = name
            break
    candidates = [n for n in pools.get(chosen_seg, []) if n not in banned and n not in used]
    if not candidates:
        candidates = [n for n in pools.get("all", []) if n not in banned and n not in used]
    if not candidates:
        return None
    start = rng.randint(0, max(0, min(14, len(candidates) - 1)))
    window = candidates[start : start + 12]
    return rng.choice(window or candidates)


def _apply_anti_repetition(
    base: dict,
    *,
    loteria: str,
    sorteo: str,
    horario: str,
    fecha: str,
    lottery_id: int,
    draw_name: str,
) -> tuple[list[str], str]:
    primary = [str(n).zfill(2) for n in (base.get("generated_numbers") or base.get("numbers") or [])]
    if len(primary) < 3:
        return primary, "sin rotación — datos insuficientes"

    recent = get_recent_recomendaciones_rd(loteria, sorteo, "", days=7)
    recent_combos = {_combo_key(r.get("numeros") or []) for r in recent}
    yesterday_nums = _yesterday_draw_numbers(lottery_id, draw_name)

    pools = _build_ranked_pools(base)
    seed = _daily_seed(fecha, loteria, sorteo, horario)
    banned = set(yesterday_nums)
    for r in recent[:2]:
        for n in r.get("numeros") or []:
            banned.add(str(n).zfill(2))

    combo = list(primary[:3])
    notes: list[str] = []
    must_rotate = _combo_key(combo) in recent_combos

    if must_rotate:
        notes.append("combinación repetida en 7 días — rotación aplicada")
        combo = []
        used: set[str] = set()
        rng = random.Random(seed)
        ranked = pools.get("all", []) or primary
        for pos in range(3):
            candidates = [
                n for n in ranked
                if n not in banned and n not in used and n not in combo
            ]
            if len(candidates) < 3:
                candidates = [
                    f"{i:02d}" for i in range(100)
                    if f"{i:02d}" not in banned and f"{i:02d}" not in used
                ]
            offset = 3 + (pos * 2)
            window = candidates[offset : offset + 12] or candidates
            pick = rng.choice(window) if window else candidates[0]
            combo.append(pick)
            used.add(pick)

    if _combo_key(combo) in recent_combos:
        rng = random.Random(seed + 1)
        ranked = [n for n in pools.get("all", []) if n not in banned]
        for i in range(3):
            alts = [n for n in ranked if n not in combo]
            if alts:
                off = 3 + i
                combo[i] = rng.choice(alts[off : off + 10] if len(alts) > off else alts)
        notes.append("segunda pasada de rotación")

    note = "; ".join(notes) if notes else "rotación diaria estable"
    return combo[:3], note


def _format_response(
    base: dict,
    combo: list[str],
    *,
    loteria: str,
    sorteo: str,
    horario: str,
    fecha: str,
    rango_dias: int,
    rotation_note: str,
    force: bool,
) -> dict:
    score = int(base.get("score") or 0)
    conf_key, conf_label = confidence_from_score(score)
    if conf_key == "bajo":
        analysis = f"{LOW_CONF_MSG} {EXPLICACION_BASE}"
    else:
        analysis = EXPLICACION_BASE

    diag = dict(base.get("analyzer_diagnostic") or {})
    diag.update({
        "loteria_exacta": loteria,
        "horario_exacto": horario,
        "fecha_analisis": fecha,
        "rango_dias": rango_dias,
        "confianza": score,
        "confianza_label": conf_label,
        "fuente_datos": "Base de datos RD multi-fuente",
        "sorteos_analizados": base.get("total_resultados_usados") or base.get("total_results") or 0,
        "algoritmo_version": ALGO_VERSION,
        "anti_repeticion": "No se repite con recomendaciones recientes",
        "rotacion_nota": rotation_note,
        "ultima_actualizacion_rd": get_last_rd_update(),
        "fuentes_disponibles": len([f for f in get_fuentes_status() if f.get("last_ok")]),
        "fuentes_fallidas": [f["label"] for f in get_fuentes_status() if f.get("last_ok") is False],
        "recalculado": force,
    })
    if (diag.get("sorteos_analizados") or 0) < 20:
        diag["datos_insuficientes"] = (
            "Faltan resultados históricos para una recomendación fuerte."
        )

    out = {
        **base,
        "ok": True,
        "generated_numbers": combo,
        "numbers": combo,
        "recommended_numbers": combo,
        "score": score,
        "confidence_level": conf_key,
        "confidence_label": conf_label,
        "analysis_text": analysis,
        "explicacion": analysis,
        "explicacion_detalle": rotation_note,
        "algorithm_version": ALGO_VERSION,
        "algoritmo_version": ALGO_VERSION,
        "analyzer_diagnostic": diag,
        "rd_inteligente": True,
        "no_garantia": True,
    }
    if conf_key == "bajo":
        out["low_confidence_warning"] = LOW_CONF_MSG
    return out


def generar_recomendacion_rd(
    loteria: str,
    sorteo: str,
    rango_dias: int | None = 90,
    fecha_actual: str | None = None,
    *,
    lottery_id: int | None = None,
    force: bool = False,
) -> dict:
    """
    Recomendación RD con motor v2 + rotación anti-repetición e historial persistido.
    """
    from services.recommendations.engine import generate_recommendation

    fecha = (fecha_actual or date.today().isoformat())[:10]
    rango = int(rango_dias or 90)
    rango = max(7, min(rango, 365))

    if lottery_id:
        lottery = get_lottery(lottery_id)
    else:
        from models import get_all_lotteries
        from services.lottery_normalize import find_lottery_in_list

        lottery = find_lottery_in_list(get_all_lotteries(), loteria, country="RD")
    if not lottery or lottery.get("country") != "RD":
        return {"ok": False, "message": f"Lotería RD no encontrada: {loteria}"}

    lottery_id = lottery["id"]
    draw_name, _, err = resolve_prediction_draw(lottery_id, draw_name=sorteo, sorteo=sorteo)
    if err or not draw_name:
        return {"ok": False, "message": err or "Sorteo no válido"}

    from lottery_schedules import get_schedule_slot, slot_draw_name

    slot = get_schedule_slot(lottery["name"], draw_name)
    horario = slot.get("time", "") if slot else ""
    if slot:
        horario = slot.get("time") or horario
    loteria_canon = lottery["name"]

    if not force:
        cached = get_recomendacion_rd_hoy(loteria_canon, draw_name, horario, fecha)
        if cached:
            nums = cached.get("numeros") or []
            return {
                "ok": True,
                "generated_numbers": nums,
                "numbers": nums,
                "recommended_numbers": nums,
                "score": cached.get("score_total") or 0,
                "confidence_level": "alto" if (cached.get("confianza") or 0) >= 80 else (
                    "medio" if (cached.get("confianza") or 0) >= 55 else "bajo"
                ),
                "confidence_label": cached.get("confianza_label") or "Media",
                "analysis_text": cached.get("explicacion") or EXPLICACION_BASE,
                "explicacion": cached.get("explicacion"),
                "algorithm_version": cached.get("algoritmo_version") or ALGO_VERSION,
                "from_cache": True,
                "analyzer_diagnostic": {
                    "fecha_analisis": fecha,
                    "rango_dias": cached.get("rango_dias"),
                    "algoritmo_version": cached.get("algoritmo_version"),
                    "anti_repeticion": "No se repite con recomendaciones recientes",
                },
            }

    base = generate_recommendation(
        lottery_id, draw_name, force_refresh=True, days=rango
    )
    if not base.get("ok"):
        msg = base.get("message") or "Datos insuficientes para recomendación."
        if "insuficiente" in msg.lower() or base.get("error") == "insufficient_history":
            base["analyzer_diagnostic"] = {
                "datos_insuficientes": (
                    "Faltan resultados históricos para una recomendación fuerte."
                ),
            }
        return base

    combo, rotation_note = _apply_anti_repetition(
        base,
        loteria=loteria_canon,
        sorteo=draw_name,
        horario=horario,
        fecha=fecha,
        lottery_id=lottery_id,
        draw_name=draw_name,
    )

    score = int(base.get("score") or 0)
    _, conf_label = confidence_from_score(score)
    explicacion = EXPLICACION_BASE
    if score < 55:
        explicacion = f"{LOW_CONF_MSG} {explicacion}"

    save_recomendacion_rd(
        fecha=fecha,
        lottery_id=lottery_id,
        loteria=loteria_canon,
        sorteo=draw_name,
        horario=horario,
        numeros=combo,
        score_total=score,
        confianza=score,
        confianza_label=conf_label,
        explicacion=explicacion,
        rango_dias=rango,
        algoritmo_version=ALGO_VERSION,
    )

    return _format_response(
        base,
        combo,
        loteria=loteria_canon,
        sorteo=draw_name,
        horario=horario,
        fecha=fecha,
        rango_dias=rango,
        rotation_note=rotation_note,
        force=force,
    )


def recalcular_todas_recomendaciones_rd(rango_dias: int = 90) -> dict:
    """Recalcula recomendaciones para loterías RD principales."""
    from services.rd_lottery_config import LOTTERY_CONFIG

    done = []
    errors = []
    for _key, cfg in LOTTERY_CONFIG.items():
        if not cfg.get("enabled", True):
            continue
        name = cfg["db_names"][0]
        for page in cfg.get("conectate_pages") or [{"draw_name": "tarde"}]:
            dn = page.get("draw_name", "tarde")
            try:
                generar_recomendacion_rd(name, dn, rango_dias=rango_dias, force=True)
                done.append(f"{name}/{dn}")
            except Exception as exc:
                errors.append(f"{name}/{dn}: {exc}")
    return {"ok": True, "recalculadas": done, "errors": errors}
