import os
import sys
import secrets
import logging
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, abort, session
from flask_login import login_user, logout_user, login_required, current_user

from config_app import (
    DEBUG,
    HOST,
    IS_PRODUCTION,
    PORT,
    SECRET_KEY as ENV_SECRET_KEY,
    validate_production_config,
)
from services.app_logging import setup_app_logging
from auth import init_auth, admin_required, User

setup_app_logging()
logger = logging.getLogger(__name__)
from models import (
    init_db,
    DISCLAIMER,
    get_all_lotteries,
    get_lottery,
    create_lottery,
    update_lottery,
    toggle_lottery,
    get_draw_times,
    create_draw_time,
    update_draw_time,
    toggle_draw_time,
    delete_draw_time,
    get_results,
    get_max_draw_date,
    get_results_for_latest_date,
    get_results_grouped_by_date,
    create_result,
    delete_result,
    toggle_result_confirmed,
    get_predictions,
    upsert_api_config,
    get_api_configs,
    parse_numbers,
    enrich_result_row,
    get_user_by_username,
    verify_user_password,
    update_last_login,
    get_all_users,
    create_user,
    update_user,
    set_user_password,
    set_user_active,
    delete_user,
    get_user_by_id,
    INITIAL_ADMIN_USERNAME,
)
from analysis import analizar_loteria_por_tanda, generar_jugada_inteligente
from lottery_schedules import (
    build_draw_buttons,
    get_lottery_schedule,
    get_schedule_slot,
    schedule_draw_order,
    slot_draw_name,
    time_12h_to_24h,
)
from importers import (
    import_csv,
    import_manual,
    sync_from_api,
    WebScraperImporter,
    refresh_lottery_results_now,
    refresh_all_rd_now,
)

app = Flask(__name__)
app.url_map.strict_slashes = False
if ENV_SECRET_KEY:
    app.secret_key = ENV_SECRET_KEY
elif IS_PRODUCTION:
    raise RuntimeError("SECRET_KEY es obligatorio cuando FLASK_ENV=production")
else:
    app.secret_key = secrets.token_hex(32)
    logger.warning("SECRET_KEY no definido; usando clave temporal (solo desarrollo).")

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)

for msg in validate_production_config():
    logger.warning("Config: %s", msg)

init_auth(app)
init_db()
logger.info("App iniciada | production=%s | db=%s", IS_PRODUCTION, os.environ.get("DATABASE_PATH", "lottery.db"))

DRAW_BUTTONS = {
    "USA": [
        {"draw_name": "Midday", "label": "Midday", "emoji": "☀️", "css": "tanda-midday"},
        {"draw_name": "Evening", "label": "Evening", "emoji": "🌙", "css": "tanda-evening"},
        {"draw_name": "Powerball draw", "label": "Powerball", "emoji": "🎱", "css": "tanda-powerball"},
        {"draw_name": "Mega Millions draw", "label": "Mega Millions", "emoji": "💫", "css": "tanda-mega"},
    ],
}

USA_ANALYSIS_TIMEOUT_SEC = 15


def _usa_analysis_log(msg: str) -> None:
    line = f"[USA ANALISIS] {msg}"
    logger.info(line)
    print(line)


def _run_usa_analysis_timed(fn, label: str = "analisis"):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    _usa_analysis_log("inicio")
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            result = fut.result(timeout=USA_ANALYSIS_TIMEOUT_SEC)
        except FutTimeout:
            _usa_analysis_log(f"timeout ({USA_ANALYSIS_TIMEOUT_SEC}s) en {label}")
            return None, "timeout"
        except Exception as exc:
            logger.exception("USA análisis %s", label)
            return None, str(exc)
    if isinstance(result, dict):
        loaded = result.get("total_results", result.get("history_count", "—"))
        _usa_analysis_log(f"resultados cargados: {loaded}")
    _usa_analysis_log("respuesta enviada")
    return result, None


def _enrich_prediction_payload(result, lottery_id, draw_name, lottery):
    """Metadatos de horario — generar_jugada_inteligente ya incluye stats."""
    if not result or not lottery:
        return result

    draws = get_draw_times(lottery_id, active_only=True)
    draw_time = next((d.get("draw_time") for d in draws if d["draw_name"] == draw_name), "")
    schedule_slot = get_schedule_slot(lottery["name"], draw_name)
    if schedule_slot:
        draw_time = time_12h_to_24h(schedule_slot["time"])

    result["schedule_label"] = _build_schedule_label(lottery, draw_name, draw_time)
    result["draw_time"] = draw_time
    if schedule_slot:
        result["time_display"] = schedule_slot["time"]
        result["draw_display"] = schedule_slot["time"]
    else:
        result["time_display"] = _format_time_12h(draw_time)
        if lottery.get("country") == "RD":
            labels = {"mañana": "Mañana", "tarde": "Tarde", "tardía": "Tardía", "noche": "Noche"}
            result["draw_display"] = labels.get(draw_name, draw_name.capitalize())
        else:
            result["draw_display"] = draw_name
    emoji = result.get("schedule_emoji") or DRAW_EMOJI_RD.get(draw_name, "🎱")
    tanda = result.get("draw_display") or draw_name
    result["schedule_label"] = f"{emoji} {tanda} — {result.get('schedule_label', lottery['name'])}"

    if not result.get("analysis_basis"):
        from analysis import ANALYSIS_BASIS_TEXT
        result["analysis_basis"] = ANALYSIS_BASIS_TEXT
    return result


def _format_time_12h(draw_time):
    if not draw_time:
        return ""
    try:
        parts = str(draw_time).strip().split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        suffix = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d} {suffix}"
    except (ValueError, IndexError):
        return draw_time


DRAW_EMOJI_RD = {
    "mañana": "🌅",
    "tarde": "🌇",
    "tardía": "🎯",
    "noche": "🌙",
}


def _build_schedule_label(lottery, draw_name, draw_time):
    time_str = _format_time_12h(draw_time)
    name = lottery.get("name", "")
    if lottery.get("country") == "RD" and time_str:
        return f"{name} {time_str}"
    if time_str:
        return f"{name} {time_str}" if name else f"{draw_name} — {time_str}"
    return draw_name or name


def _user_badge_info(row):
    u = User(row)
    badge_class, badge_label = u.status_badge()
    return {**row, "badge_class": badge_class, "badge_label": badge_label}


@app.before_request
def enforce_access():
    if request.endpoint in (None, "login", "logout", "static", "health"):
        return
    if not current_user.is_authenticated:
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "No autenticado. Inicia sesión."}), 401
        return redirect(url_for("login", next=request.url))
    allowed, reason = current_user.check_access()
    if allowed:
        return
    logout_user()
    if reason == "blocked":
        msg = "Acceso bloqueado por administrador."
    else:
        msg = "Tu acceso ha vencido."
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": msg}), 403
    flash(msg, "danger")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_user.is_authenticated and not request.args.get("cambiar"):
            ok, _ = current_user.check_access()
            if ok:
                return redirect(request.args.get("next") or url_for("index"))
        return render_template(
            "login.html",
            disclaimer=DISCLAIMER,
            next_url=request.args.get("next"),
            sesion_activa=current_user.is_authenticated,
            usuario_activo=current_user.username if current_user.is_authenticated else "",
        )

    # POST: siempre limpiar sesión anterior antes de iniciar otra cuenta
    logout_user()
    session.clear()

    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    row = get_user_by_username(username)

    if not row or not verify_user_password(row, password):
        flash("Usuario o contraseña incorrectos.", "danger")
        return render_template(
            "login.html",
            disclaimer=DISCLAIMER,
            next_url=request.form.get("next"),
            sesion_activa=False,
            usuario_activo="",
        )

    user = User(row)
    if not user.is_active:
        flash("Tu acceso está bloqueado. Contacta al administrador.", "danger")
        return render_template(
            "login.html", disclaimer=DISCLAIMER, next_url=request.form.get("next"),
            sesion_activa=False, usuario_activo="",
        )

    if user.is_expired():
        flash("Tu acceso ha vencido.", "warning")
        return render_template(
            "login.html", disclaimer=DISCLAIMER, next_url=request.form.get("next"),
            sesion_activa=False, usuario_activo="",
        )

    login_user(user, remember=False, fresh=True)
    session.permanent = True
    session["user_id"] = user.id
    session["username"] = user.username
    session["role"] = user.role
    update_last_login(user.id)
    next_url = request.form.get("next") or request.args.get("next")
    return redirect(next_url or url_for("index"))


@app.route("/logout")
def logout():
    logout_user()
    session.clear()
    resp = redirect(url_for("login"))
    remember_name = app.config.get("REMEMBER_COOKIE_NAME", "remember_token")
    resp.delete_cookie(remember_name)
    flash("Sesión cerrada correctamente.", "info")
    return resp


@app.route("/health")
def health():
    """Liveness/readiness para Render, balanceadores, etc."""
    from models import DATABASE, get_connection

    db_ok = False
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception as exc:
        logger.error("Health DB check failed: %s", exc)
    status = 200 if db_ok else 503
    return jsonify({
        "ok": db_ok,
        "status": "healthy" if db_ok else "degraded",
        "production": IS_PRODUCTION,
        "database": DATABASE,
    }), status


@app.route("/debug/system")
@admin_required
def debug_system():
    """Diagnóstico general del sistema (solo admin)."""
    from models import DATABASE, get_all_lotteries, get_all_users

    lotteries = get_all_lotteries(active_only=False)
    users = get_all_users()
    return jsonify({
        "ok": True,
        "production": IS_PRODUCTION,
        "database": DATABASE,
        "lotteries_count": len(lotteries),
        "users_count": len(users),
        "python_version": sys.version.split()[0],
    })


@app.route("/")
@login_required
def index():
    lotteries = get_all_lotteries(active_only=True)
    return render_template("index.html", lotteries=lotteries, disclaimer=DISCLAIMER)


@app.route("/api/lotteries")
def api_lotteries():
    country = request.args.get("country")
    state = request.args.get("state")
    lotteries = get_all_lotteries(active_only=True)
    if country:
        lotteries = [l for l in lotteries if l["country"] == country]
    if state:
        lotteries = [l for l in lotteries if (l.get("state") or "") == state]
    return jsonify({"ok": True, "lotteries": lotteries})


@app.route("/api/states")
def api_states():
    country = request.args.get("country", "USA")
    lotteries = get_all_lotteries(active_only=True)
    states = sorted({l["state"] for l in lotteries if l["country"] == country and l.get("state")})
    return jsonify({"ok": True, "states": states})


@app.route("/api/draw-times")
def api_draw_times():
    lottery_id = request.args.get("lottery_id", type=int)
    if not lottery_id:
        return jsonify({"ok": False, "message": "lottery_id requerido"})
    lottery = get_lottery(lottery_id)
    if not lottery:
        return jsonify({"ok": False, "message": "Lotería no encontrada"})
    draws = get_draw_times(lottery_id, active_only=True)
    scheduled = build_draw_buttons(lottery, draws)
    if scheduled is not None:
        filtered = []
        for b in scheduled:
            enriched = dict(b)
            enriched["schedule_label"] = _build_schedule_label(
                lottery, b["draw_name"], b.get("draw_time", "")
            )
            filtered.append(enriched)
        return jsonify({
            "ok": True,
            "draw_times": draws,
            "buttons": filtered,
            "lottery": lottery,
            "uses_schedule": True,
        })

    draw_map = {d["draw_name"]: d for d in draws}
    buttons = DRAW_BUTTONS.get(lottery["country"], [])
    available = set(draw_map.keys())
    filtered = []
    for b in buttons:
        if b["draw_name"] not in available:
            continue
        dt = draw_map.get(b["draw_name"], {})
        enriched = dict(b)
        enriched["draw_time"] = dt.get("draw_time", "")
        enriched["time_display"] = _format_time_12h(enriched["draw_time"])
        enriched["schedule_label"] = _build_schedule_label(
            lottery, b["draw_name"], enriched["draw_time"]
        )
        filtered.append(enriched)
    if not filtered:
        for d in draws:
            filtered.append({
                "draw_name": d["draw_name"],
                "label": d["draw_name"].capitalize(),
                "emoji": DRAW_EMOJI_RD.get(d["draw_name"], "🎱"),
                "css": "tanda-default",
                "draw_time": d.get("draw_time", ""),
                "time_display": _format_time_12h(d.get("draw_time", "")),
                "schedule_label": _build_schedule_label(
                    lottery, d["draw_name"], d.get("draw_time", "")
                ),
            })
    return jsonify({
        "ok": True,
        "draw_times": draws,
        "buttons": filtered,
        "lottery": lottery,
        "uses_schedule": False,
    })


@app.route("/api/results")
def api_results():
    from models import get_results_history

    lottery_id = request.args.get("lottery_id", type=int)
    draw_name = request.args.get("draw_name") or None
    if draw_name:
        draw_name = draw_name.strip() or None
    limit = request.args.get("limit", 10, type=int)
    mode = request.args.get("mode", "latest")
    if not lottery_id:
        return jsonify({"ok": False, "message": "lottery_id requerido"})
    lottery = get_lottery(lottery_id)
    latest_date = None
    groups = None
    load_error = None

    days_param = request.args.get("days", type=int)
    # 365 en UI = “Todo” (sin cutoff de fecha)
    if days_param == 365:
        limit_days = 0
    elif days_param:
        limit_days = days_param
    else:
        limit_days = max(limit, 30)

    today_iso = datetime.now().strftime("%Y-%m-%d")

    if lottery and lottery.get("country") == "RD" and mode == "all":
        groups = get_results_grouped_by_date(
            lottery_id, limit_days=limit_days, draw_name=draw_name
        )
        latest_date = get_max_draw_date(lottery_id)
        results = []
    elif lottery and lottery.get("country") == "RD" and mode == "latest":
        results, latest_date = get_results_for_latest_date(lottery_id, draw_name)
        results = [r for r in results if r.get("draw_date") == today_iso]
        if not results:
            results = get_results_history(
                lottery_id, draw_name=draw_name, days=1, limit=50
            )
            results = [r for r in results if r.get("draw_date") == today_iso]
            if results:
                latest_date = today_iso
    elif lottery and lottery.get("country") == "RD":
        results = get_results_history(
            lottery_id, draw_name=draw_name, days=limit_days or 30, limit=500
        )
        latest_date = results[0].get("draw_date") if results else None
    else:
        results = get_results(lottery_id, draw_name, limit)

    schedule = get_lottery_schedule(lottery["name"]) if lottery else None
    allowed_draws = None
    if schedule:
        allowed_draws = {slot_draw_name(s) for s in schedule}

    if allowed_draws is not None:
        results = [r for r in results if r.get("draw_name") in allowed_draws]
        results.sort(key=lambda r: schedule_draw_order(r.get("draw_name")))

    for r in results:
        enrich_result_row(r, lottery)
        slot = get_schedule_slot(lottery["name"], r.get("draw_name")) if lottery else None
        r["time_display"] = slot["time"] if slot else _format_time_12h(r.get("draw_time", ""))

    if groups is not None:
        for g in groups:
            if allowed_draws is not None:
                g["results"] = [
                    r for r in g["results"] if r.get("draw_name") in allowed_draws
                ]
                g["results"].sort(key=lambda r: schedule_draw_order(r.get("draw_name")))
            for r in g["results"]:
                enrich_result_row(r, lottery)
                slot = get_schedule_slot(lottery["name"], r.get("draw_name")) if lottery else None
                r["time_display"] = slot["time"] if slot else _format_time_12h(r.get("draw_time", ""))

    if lottery and lottery.get("country") == "USA":
        results.sort(
            key=lambda r: (
                0 if "results-hub" in (r.get("source_url") or "") else 1,
                r.get("draw_date", ""),
            ),
            reverse=True,
        )

    total_in_db = 0
    if lottery_id:
        from models import get_results as _gr
        total_in_db = len(_gr(lottery_id, draw_name=draw_name, limit=500))

    payload = {
        "ok": True,
        "results": results,
        "mode": mode,
        "draw_name": draw_name,
        "total_in_db": total_in_db,
        "has_results": bool(results) or bool(groups),
        "load_error": load_error,
        "lottery_name": lottery.get("name") if lottery else "",
    }
    if latest_date:
        payload["latest_date"] = latest_date
    if groups is not None:
        payload["groups"] = groups
    return jsonify(payload)


@app.route("/debug/lottery/<source>")
@admin_required
def debug_lottery_source(source):
    from services.rd_debug import debug_lottery_source as run_debug
    return jsonify(run_debug(source))


@app.route("/debug/resultados")
@admin_required
def debug_resultados():
    from services.rd_debug import debug_resultados_general
    return jsonify(debug_resultados_general())


@app.route("/debug/history")
@admin_required
def debug_history():
    from services.history_fetch import debug_history_status
    return jsonify(debug_history_status())


@app.route("/debug/new-lotteries")
@admin_required
def debug_new_lotteries():
    from services.new_lotteries_debug import debug_new_lotteries as run_debug
    return jsonify(run_debug())


def _api_actualizar_resultados_payload(data=None):
    """Despacho estricto US vs DO — sin mezclar Illinois con RD."""
    from services.actualizar_resultados import (
        actualizar_resultados_rd,
        actualizar_resultados_usa,
        es_pais_do,
        es_pais_us,
    )

    data = data or {}
    pais = (
        data.get("pais")
        or data.get("country")
        or request.form.get("pais")
        or request.form.get("country")
        or ""
    ).strip()
    state = (data.get("state") or request.form.get("state") or "").strip()
    loteria = (
        data.get("loteria")
        or data.get("lottery")
        or request.form.get("loteria")
        or request.form.get("lottery")
        or ""
    ).strip()
    refresh_all_rd = data.get("refresh_all_rd") or request.form.get("refresh_all_rd")
    refresh_all_usa = data.get("refresh_all_usa") or request.form.get("refresh_all_usa")
    days = int(data.get("days") or request.form.get("days") or 30)

    if es_pais_us(pais):
        return actualizar_resultados_usa(
            loteria or None,
            state=state or "Illinois",
            days=days,
            refresh_all=bool(refresh_all_usa or not loteria),
        )

    if es_pais_do(pais):
        return actualizar_resultados_rd(
            loteria or None,
            days=days,
            refresh_all=bool(refresh_all_rd or not loteria),
        )

    return {
        "ok": False,
        "message": f"País no soportado: {pais}. Use US/USA o DO/RD.",
        "mensaje": f"País no soportado: {pais}. Use US/USA o DO/RD.",
    }


def _format_actualizar_api_response(result: dict) -> tuple[dict, int]:
    """JSON estándar para /api/resultados/actualizar (+ alias actualizar-ahora)."""
    if not isinstance(result, dict):
        return {"ok": False, "error": "Respuesta inválida del servicio de actualización"}, 500

    imported = int(result.get("imported") or 0)
    updated = int(result.get("updated") or 0)
    saved = int(result.get("saved_count") or (imported + updated))
    raw_msg = (result.get("mensaje") or result.get("message") or "").strip()
    errors = list(result.get("errors") or [])

    base = {**result}
    base["imported"] = imported
    base["updated"] = updated
    base["saved_count"] = saved

    fuente = (result.get("fuente") or result.get("source") or "").lower()

    if result.get("ok"):
        if result.get("used_db_fallback") or result.get("status") == "cached_fallback":
            mensaje = raw_msg or "No se pudo actualizar ahora; se muestran resultados guardados."
            base.update({
                "ok": True,
                "warning": True,
                "cache": True,
                "mensaje": mensaje,
                "message": mensaje,
            })
            return base, 200

        if result.get("cache") or result.get("cache_used") or result.get("from_json_cache"):
            mensaje = raw_msg or "No se pudo actualizar ahora; se muestran resultados guardados."
            base.update({
                "ok": True,
                "warning": True,
                "cache": True,
                "mensaje": mensaje,
                "message": mensaje,
            })
            return base, 200

        if fuente == "lotteryusa" or (result.get("warning") and "lotteryusa" in fuente):
            mensaje = raw_msg or "Fuente principal falló. Se usó LotteryUSA."
            base.update({
                "ok": True,
                "warning": True,
                "fuente": "lotteryusa",
                "mensaje": mensaje,
                "message": mensaje,
            })
            return base, 200

        if fuente in ("illinoislottery", "illinois_results_hub", "illinois_lottery"):
            base["fuente"] = "illinoislottery"

        mensaje = raw_msg or "Resultados actualizados correctamente"
        base.update({
            "ok": True,
            "warning": bool(result.get("partial") or result.get("warning")),
            "mensaje": mensaje,
            "message": mensaje,
        })
        if not base.get("fuente") and fuente:
            base["fuente"] = fuente
        return base, 200

    err = raw_msg
    if not err and errors:
        err = str(errors[0])
    if not err:
        err = "Error al actualizar resultados"

    if saved > 0:
        mensaje = "No se pudo actualizar ahora, pero se muestran resultados guardados."
        base.update({
            "ok": True,
            "warning": True,
            "mensaje": mensaje,
            "message": mensaje,
            "used_db_fallback": True,
            "saved_count": saved,
        })
        return base, 200

    base.update({"ok": False, "error": err, "message": err, "mensaje": err})
    return base, 500


def _actualizar_resultados_api(data=None):
    """Lógica compartida POST /api/resultados/actualizar y /actualizar-ahora."""
    data = data or {}
    pais = (
        data.get("pais")
        or data.get("country")
        or request.form.get("pais")
        or request.form.get("country")
        or ""
    ).strip()
    loteria = (
        data.get("loteria")
        or data.get("lottery")
        or request.form.get("loteria")
        or request.form.get("lottery")
        or ""
    ).strip()

    logger.info(
        "[API] Iniciando actualización | país=%s | lotería=%s | path=%s",
        pais or "?",
        loteria or "TODAS",
        request.path,
    )

    try:
        result = _api_actualizar_resultados_payload(data)
        payload, status = _format_actualizar_api_response(result)
        logger.info(
            "[API] Actualización finalizada | ok=%s | imported=%s | updated=%s | warning=%s | status=%s",
            payload.get("ok"),
            payload.get("imported", 0),
            payload.get("updated", 0),
            payload.get("warning"),
            status,
        )
        if payload.get("ok") is False:
            logger.error("[API] Error scraper: %s", payload.get("error"))
        elif errors := payload.get("errors"):
            if errors:
                logger.warning("[API] Advertencias scraper: %s", errors[:3])
        return payload, status
    except Exception as exc:
        logger.exception("[API] Excepción actualizando resultados")
        return {"ok": False, "error": str(exc), "message": str(exc), "mensaje": str(exc)}, 500


@app.route("/api/resultados/actualizar", methods=["POST"])
@app.route("/api/resultados/actualizar-ahora", methods=["POST"])
@login_required
def api_actualizar_resultados_ahora():
    if not current_user.is_admin():
        return jsonify({
            "ok": False,
            "error": "Solo administradores pueden actualizar resultados.",
            "message": "Solo administradores pueden actualizar resultados.",
        }), 403
    data = request.get_json(silent=True) or {}
    payload, status = _actualizar_resultados_api(data)
    return jsonify(payload), status


def _run_leidsa_update():
    from services.leidsa_service import update_leidsa_now

    return update_leidsa_now()


@app.route("/admin/resultados/leidsa/actualizar", methods=["POST"])
@admin_required
def admin_actualizar_leidsa():
    result = _run_leidsa_update()
    if result.get("ok"):
        flash(result.get("message", "LEIDSA actualizada."), "success")
    else:
        flash(result.get("message", "Leidsa no respondió, intenta de nuevo"), "danger")
    return redirect(url_for("admin") + "#tabApi")


@app.route("/api/resultados/rd/actualizar-historial-completo", methods=["POST"])
@admin_required
def api_actualizar_rd_historial_completo():
    from services.history_fetch import fetch_all_rd_history

    data = request.get_json(silent=True) or {}
    days = int(data.get("days") or request.form.get("days") or 90)
    result = fetch_all_rd_history(days=days)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.route("/admin/resultados/rd/actualizar", methods=["POST"])
@admin_required
def admin_actualizar_rd():
    result = refresh_all_rd_now(days=30)
    if result.get("ok"):
        flash(result.get("message", "Resultados RD actualizados."), "success")
    else:
        flash(result.get("message", "Error al actualizar RD."), "danger")
    return redirect(url_for("admin") + "#tabApi")


@app.route("/api/resultados/leidsa/actualizar", methods=["POST"])
@admin_required
def api_actualizar_leidsa():
    result = _run_leidsa_update()
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.route("/api/resultados/leidsa")
@login_required
def api_resultados_leidsa():
    from services.leidsa_service import get_leidsa_dashboard

    fecha = request.args.get("fecha") or request.args.get("fecha_rd")
    days = request.args.get("days", type=int)
    data = get_leidsa_dashboard(fecha, history_days=days)
    # Siempre 200 con payload JSON (evita panel roto si hay datos en BD)
    return jsonify(data), 200


@app.route("/admin/resultados/leidsa/actualizar-historial", methods=["POST"])
@admin_required
def admin_actualizar_leidsa_historial():
    from services.leidsa_history import update_leidsa_history

    days = request.form.get("days", type=int) or 90
    result = update_leidsa_history(days=days)
    if result.get("ok"):
        flash(result.get("message", "Historial LEIDSA actualizado."), "success")
    else:
        flash(result.get("message", "Error al actualizar historial LEIDSA."), "danger")
    return redirect(url_for("admin") + "#tabApi")


@app.route("/api/resultados/leidsa/actualizar-historial", methods=["POST"])
@admin_required
def api_actualizar_leidsa_historial():
    from services.leidsa_history import update_leidsa_history

    data = request.get_json(silent=True) or {}
    days = data.get("days") or request.form.get("days", type=int) or 90
    result = update_leidsa_history(days=int(days))
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.errorhandler(404)
def not_found(err):
    if request.path.startswith("/api/") or request.path.startswith("/debug/"):
        return jsonify({"ok": False, "message": "Recurso no encontrado."}), 404
    return render_template("login.html", disclaimer=DISCLAIMER), 404


@app.errorhandler(500)
def server_error(err):
    logger.exception("Error interno: %s", err)
    if request.path.startswith("/api/") or request.path.startswith("/debug/"):
        msg = "Error interno del servidor." if IS_PRODUCTION else str(err)
        return jsonify({"ok": False, "message": msg}), 500
    if current_user.is_authenticated:
        flash("Ocurrió un error interno. Intenta de nuevo.", "danger")
        return redirect(url_for("index"))
    return redirect(url_for("login"))


@app.route("/debug/leidsa")
@admin_required
def debug_leidsa():
    from services.leidsa_service import debug_leidsa as run_debug
    return jsonify(run_debug())


@app.route("/debug/leidsa/dropdowns")
@admin_required
def debug_leidsa_dropdowns():
    from services.leidsa_history import debug_leidsa_dropdowns as run_debug
    return jsonify(run_debug())


@app.route("/debug/leidsa/history")
@admin_required
def debug_leidsa_history():
    from services.leidsa_history import debug_leidsa_history_sample as run_debug

    days = request.args.get("days", 90, type=int)
    return jsonify(run_debug(days=days))


@app.route("/debug/recomendacion/leidsa")
@admin_required
def debug_recomendacion_leidsa():
    from analysis import debug_leidsa_recommendation

    lottery = request.args.get("lottery", "")
    draw = request.args.get("draw", "noche")
    return jsonify(debug_leidsa_recommendation(lottery, draw))


@app.route("/api/analisis/leidsa")
def api_analisis_leidsa():
    from services.leidsa_service import get_leidsa_analysis

    tipo = request.args.get("tipo", "recomendado")
    draw_name = request.args.get("draw_name") or request.args.get("draw")
    if tipo not in ("caliente", "frio", "atrasado", "recomendado"):
        return jsonify({"ok": False, "message": "tipo inválido"}), 400
    result = get_leidsa_analysis(tipo, draw_name=draw_name or None)
    return jsonify(result)


@app.route("/api/prediction")
def api_prediction():
    try:
        lottery_id = request.args.get("lottery_id", type=int)
        draw_name = request.args.get("draw_name", "").strip()
        if not lottery_id or not draw_name:
            return jsonify({"ok": False, "message": "lottery_id y draw_name son requeridos"}), 400

        lottery = get_lottery(lottery_id)
        if not lottery:
            return jsonify({"ok": False, "message": "Lotería no encontrada.", "error": "not_found"}), 404

        def build():
            result = generar_jugada_inteligente(lottery_id, draw_name)
            return _enrich_prediction_payload(result, lottery_id, draw_name, lottery)

        if lottery.get("country") == "USA":
            result, err = _run_usa_analysis_timed(build, "prediction")
            if err:
                return jsonify({
                    "ok": False,
                    "message": "⚠️ No se pudo completar el análisis.",
                    "error": err,
                }), 500
            status = 200 if result.get("ok") else 400
            return jsonify(result), status

        result = build()
        status = 200 if result.get("ok") else 400
        return jsonify(result), status
    except Exception as exc:
        logger.exception("api_prediction")
        return jsonify({
            "ok": False,
            "message": "⚠️ No se pudo completar el análisis.",
            "error": str(exc),
        }), 500


@app.route("/api/analysis")
def api_analysis():
    try:
        lottery_id = request.args.get("lottery_id", type=int)
        draw_name = request.args.get("draw_name", "").strip()
        if not lottery_id or not draw_name:
            return jsonify({"ok": False, "message": "lottery_id y draw_name son requeridos"}), 400

        lottery = get_lottery(lottery_id)

        def run_analysis():
            return analizar_loteria_por_tanda(lottery_id, draw_name)

        if lottery and lottery.get("country") == "USA":
            result, err = _run_usa_analysis_timed(run_analysis, "analysis")
            if err:
                return jsonify({
                    "ok": False,
                    "message": "⚠️ No se pudo completar el análisis.",
                    "error": err,
                }), 500
        else:
            result = run_analysis()

        if result and result.get("ok"):
            for key in ("_all_nums", "_freq", "_config", "_per_draw"):
                result.pop(key, None)
        return jsonify(result or {"ok": False, "message": "Error en análisis"})
    except Exception as exc:
        logger.exception("api_analysis")
        return jsonify({
            "ok": False,
            "message": "⚠️ No se pudo completar el análisis.",
            "error": str(exc),
        }), 500


# --- Admin usuarios ---

@app.route("/admin/usuarios")
@admin_required
def admin_usuarios():
    rows = get_all_users()
    users = [_user_badge_info(r) for r in rows]
    return render_template("admin_usuarios.html", users=users, disclaimer=DISCLAIMER)


@app.route("/admin/usuarios/crear", methods=["POST"])
@admin_required
def admin_usuarios_crear():
    username = (request.form.get("username") or "").strip().lower()
    password = request.form.get("password") or ""
    if not username or len(password) < 6:
        flash("Usuario y contraseña (mín. 6 caracteres) son requeridos.", "danger")
        return redirect(url_for("admin_usuarios"))
    if get_user_by_username(username):
        flash(f"El usuario '{username}' ya existe.", "warning")
        return redirect(url_for("admin_usuarios"))
    expires = request.form.get("expires_at") or None
    create_user(
        username=username,
        password=password,
        nombre=request.form.get("nombre", ""),
        email=request.form.get("email", ""),
        role=request.form.get("role", "usuario"),
        is_active=1 if request.form.get("is_active") else 0,
        expires_at=expires,
    )
    flash(f"Usuario '{username}' creado.", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:user_id>/editar", methods=["POST"])
@admin_required
def admin_usuarios_editar(user_id):
    if user_id == current_user.id and request.form.get("role") != "admin":
        flash("No puedes quitarte el rol admin a ti mismo.", "warning")
        return redirect(url_for("admin_usuarios"))
    update_user(
        user_id,
        nombre=request.form.get("nombre", ""),
        email=request.form.get("email", ""),
        role=request.form.get("role"),
        expires_at=request.form.get("expires_at") or None,
        clear_expiry=bool(request.form.get("clear_expiry")),
    )
    flash("Usuario actualizado.", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:user_id>/password", methods=["POST"])
@admin_required
def admin_usuarios_password(user_id):
    password = request.form.get("password") or ""
    if len(password) < 6:
        flash("La contraseña debe tener al menos 6 caracteres.", "danger")
        return redirect(url_for("admin_usuarios"))
    set_user_password(user_id, password)
    flash("Contraseña actualizada.", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:user_id>/bloquear", methods=["POST"])
@admin_required
def admin_usuarios_bloquear(user_id):
    if user_id == current_user.id:
        flash("No puedes bloquearte a ti mismo.", "warning")
        return redirect(url_for("admin_usuarios"))
    set_user_active(user_id, False)
    flash("Usuario bloqueado.", "warning")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:user_id>/activar", methods=["POST"])
@admin_required
def admin_usuarios_activar(user_id):
    set_user_active(user_id, True)
    flash("Usuario activado.", "success")
    return redirect(url_for("admin_usuarios"))


@app.route("/admin/usuarios/<int:user_id>/eliminar", methods=["POST"])
@admin_required
def admin_usuarios_eliminar(user_id):
    if user_id == current_user.id:
        flash("No puedes eliminar tu propia cuenta.", "warning")
        return redirect(url_for("admin_usuarios"))
    target = get_user_by_id(user_id)
    if target and target.get("username") == INITIAL_ADMIN_USERNAME:
        flash("No se puede eliminar el administrador principal.", "danger")
        return redirect(url_for("admin_usuarios"))
    delete_user(user_id)
    flash("Usuario eliminado.", "success")
    return redirect(url_for("admin_usuarios"))


# --- Admin ---

@app.route("/admin")
@admin_required
def admin():
    lotteries = get_all_lotteries()
    results = get_results(limit=100)
    for r in results:
        r["numbers_list"] = parse_numbers(r["numbers"])
    predictions = get_predictions(limit=50)
    api_configs = get_api_configs()
    return render_template(
        "admin.html",
        lotteries=lotteries,
        results=results,
        predictions=predictions,
        api_configs=api_configs,
        disclaimer=DISCLAIMER,
    )


@app.route("/admin/lottery/add", methods=["POST"])
@admin_required
def admin_add_lottery():
    create_lottery(
        request.form.get("country"),
        request.form.get("state"),
        request.form.get("name"),
        request.form.get("type"),
        1 if request.form.get("active") else 0,
    )
    flash("Lotería agregada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/lottery/edit/<int:lottery_id>", methods=["POST"])
@admin_required
def admin_edit_lottery(lottery_id):
    update_lottery(
        lottery_id,
        request.form.get("country"),
        request.form.get("state"),
        request.form.get("name"),
        request.form.get("type"),
        1 if request.form.get("active") else 0,
    )
    flash("Lotería actualizada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/lottery/toggle/<int:lottery_id>", methods=["POST"])
@admin_required
def admin_toggle_lottery(lottery_id):
    toggle_lottery(lottery_id)
    flash("Estado de lotería cambiado.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/draw/add", methods=["POST"])
@admin_required
def admin_add_draw():
    create_draw_time(
        int(request.form.get("lottery_id")),
        request.form.get("draw_name"),
        request.form.get("draw_time"),
        request.form.get("timezone", "America/New_York"),
        1 if request.form.get("active") else 0,
    )
    flash("Tanda agregada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/draw/edit/<int:draw_id>", methods=["POST"])
@admin_required
def admin_edit_draw(draw_id):
    update_draw_time(
        draw_id,
        request.form.get("draw_name"),
        request.form.get("draw_time"),
        request.form.get("timezone"),
        1 if request.form.get("active") else 0,
    )
    flash("Tanda actualizada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/draw/toggle/<int:draw_id>", methods=["POST"])
@admin_required
def admin_toggle_draw(draw_id):
    toggle_draw_time(draw_id)
    flash("Estado de tanda cambiado.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/draw/delete/<int:draw_id>", methods=["POST"])
@admin_required
def admin_delete_draw(draw_id):
    delete_draw_time(draw_id)
    flash("Tanda eliminada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/result/add", methods=["POST"])
@admin_required
def admin_add_result():
    result = import_manual(request.form)
    if result.get("ok"):
        flash("Resultado agregado.", "success")
    else:
        flash(result.get("message", "Error al agregar resultado."), "danger")
    return redirect(url_for("admin"))


@app.route("/admin/result/delete/<int:result_id>", methods=["POST"])
@admin_required
def admin_delete_result(result_id):
    delete_result(result_id)
    flash("Resultado eliminado.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/result/confirm/<int:result_id>", methods=["POST"])
@admin_required
def admin_confirm_result(result_id):
    toggle_result_confirmed(result_id)
    flash("Estado de confirmación actualizado.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/import/csv", methods=["POST"])
@admin_required
def admin_import_csv():
    file = request.files.get("csv_file")
    if not file or not file.filename:
        flash("Seleccione un archivo CSV.", "danger")
        return redirect(url_for("admin"))
    content = file.read()
    result = import_csv(content)
    msg = f"Importados: {result['imported']} registros."
    if result["errors"]:
        msg += f" Errores: {len(result['errors'])}"
    flash(msg, "success" if result["imported"] else "warning")
    return redirect(url_for("admin"))


@app.route("/admin/prediction/generate", methods=["POST"])
@admin_required
def admin_generate_prediction():
    lottery_id = int(request.form.get("lottery_id"))
    draw_name = request.form.get("draw_name")
    result = generar_jugada_inteligente(lottery_id, draw_name)
    if result.get("ok"):
        flash(f"Recomendación generada: {' - '.join(result['generated_numbers'])}", "success")
    else:
        flash(result.get("message", "Error al generar."), "danger")
    return redirect(url_for("admin"))


@app.route("/admin/api/config", methods=["POST"])
@admin_required
def admin_api_config():
    upsert_api_config(
        request.form.get("source_name"),
        request.form.get("api_url"),
        request.form.get("api_key"),
        1 if request.form.get("active") else 0,
    )
    flash("Configuración API guardada.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/api/sync/<source_name>", methods=["POST"])
@admin_required
def admin_api_sync(source_name):
    result = sync_from_api(source_name)
    if result.get("ok"):
        flash(f"Sincronización API exitosa desde {source_name}.", "success")
    else:
        flash(result.get("message", "Error en sincronización."), "warning")
    return redirect(url_for("admin"))


@app.route("/admin/scraper/test", methods=["POST"])
@admin_required
def admin_scraper_test():
    source = request.form.get("source_key", "conectate_rd")
    scraper = WebScraperImporter(source)
    result = scraper.test_connection()
    if result.get("ok"):
        flash(result.get("message", "Conexión exitosa."), "success")
    else:
        flash(result.get("message", "Error en scraper."), "danger")
    return redirect(url_for("admin"))


@app.route("/admin/scraper/import", methods=["POST"])
@admin_required
def admin_scraper_import():
    source = request.form.get("source_key", "conectate_rd")
    days_back = request.form.get("days_back", 60, type=int)
    max_pages = request.form.get("max_pages", 5, type=int)
    scraper = WebScraperImporter(source)
    result = scraper.import_all(days_back=days_back, max_pages=max_pages)
    if result.get("ok"):
        msg = result.get("message", "Importación completada.")
        if result.get("errors"):
            msg += f" Advertencias: {len(result['errors'])}."
        flash(msg, "success" if result.get("imported", 0) else "warning")
    else:
        flash(result.get("message", "Error en importación."), "danger")
    return redirect(url_for("admin"))


def _verify_api_routes_registered() -> None:
    """Debe ejecutarse después de registrar todas las rutas (@app.route)."""
    required = ("/api/resultados/actualizar", "/api/resultados/actualizar-ahora")
    rules = {r.rule for r in app.url_map.iter_rules()}
    for route in required:
        if route not in rules:
            logger.error("Ruta API faltante: %s", route)
        else:
            logger.info("Ruta API registrada: POST %s", route)


_verify_api_routes_registered()

if __name__ == "__main__":
    app.run(debug=DEBUG, host=HOST, port=PORT)
