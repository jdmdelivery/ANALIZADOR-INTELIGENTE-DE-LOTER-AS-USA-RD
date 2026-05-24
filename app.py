import os
import secrets
from datetime import timedelta

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import login_user, logout_user, login_required, current_user

from auth import init_auth, admin_required, User
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
from importers import import_csv, import_manual, sync_from_api, WebScraperImporter, refresh_lottery_results_now

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=12)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=7)

init_auth(app)
init_db()

DRAW_BUTTONS = {
    "RD": [
        {"draw_name": "mañana", "label": "Mañana", "emoji": "🌅", "css": "tanda-manana"},
        {"draw_name": "tarde", "label": "Tarde", "emoji": "🌇", "css": "tanda-tarde"},
        {"draw_name": "tardía", "label": "Tardía", "emoji": "🎯", "css": "tanda-tardia"},
        {"draw_name": "noche", "label": "Noche", "emoji": "🌙", "css": "tanda-noche"},
    ],
    "USA": [
        {"draw_name": "Midday", "label": "Midday", "emoji": "☀️", "css": "tanda-midday"},
        {"draw_name": "Evening", "label": "Evening", "emoji": "🌙", "css": "tanda-evening"},
        {"draw_name": "Powerball draw", "label": "Powerball", "emoji": "🎱", "css": "tanda-powerball"},
        {"draw_name": "Mega Millions draw", "label": "Mega Millions", "emoji": "💫", "css": "tanda-mega"},
    ],
}


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
    if request.endpoint in (None, "login", "static"):
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
    if current_user.is_authenticated:
        ok, _ = current_user.check_access()
        if ok:
            return redirect(request.args.get("next") or url_for("index"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_user_by_username(username)

        if not row or not verify_user_password(row, password):
            flash("Usuario o contraseña incorrectos.", "danger")
            return render_template(
                "login.html",
                disclaimer=DISCLAIMER,
                next_url=request.form.get("next"),
            )

        user = User(row)
        if not user.is_active:
            flash("Tu acceso está bloqueado. Contacta al administrador.", "danger")
            return render_template("login.html", disclaimer=DISCLAIMER, next_url=request.form.get("next"))

        if user.is_expired():
            flash("Tu acceso ha vencido.", "warning")
            return render_template("login.html", disclaimer=DISCLAIMER, next_url=request.form.get("next"))

        login_user(user, remember=True)
        update_last_login(user.id)
        next_url = request.form.get("next") or request.args.get("next")
        return redirect(next_url or url_for("index"))

    return render_template(
        "login.html",
        disclaimer=DISCLAIMER,
        next_url=request.args.get("next"),
    )


@app.route("/logout")
def logout():
    logout_user()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("login"))


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
    return jsonify({"ok": True, "draw_times": draws, "buttons": filtered, "lottery": lottery})


@app.route("/api/results")
def api_results():
    lottery_id = request.args.get("lottery_id", type=int)
    draw_name = request.args.get("draw_name")
    limit = request.args.get("limit", 10, type=int)
    mode = request.args.get("mode", "latest")
    if not lottery_id:
        return jsonify({"ok": False, "message": "lottery_id requerido"})
    lottery = get_lottery(lottery_id)
    latest_date = None
    groups = None

    if lottery and lottery.get("country") == "RD" and mode == "all":
        groups = get_results_grouped_by_date(lottery_id, limit_days=max(limit, 30))
        latest_date = get_max_draw_date(lottery_id)
        results = []
    elif lottery and lottery.get("country") == "RD":
        results, latest_date = get_results_for_latest_date(lottery_id, draw_name)
    else:
        results = get_results(lottery_id, draw_name, limit)

    for r in results:
        enrich_result_row(r, lottery)
        r["time_display"] = _format_time_12h(r.get("draw_time", ""))

    if groups is not None:
        for g in groups:
            for r in g["results"]:
                enrich_result_row(r, lottery)
                r["time_display"] = _format_time_12h(r.get("draw_time", ""))

    if lottery and lottery.get("country") == "USA":
        results.sort(
            key=lambda r: (
                0 if "results-hub" in (r.get("source_url") or "") else 1,
                r.get("draw_date", ""),
            ),
            reverse=True,
        )

    payload = {"ok": True, "results": results, "mode": mode}
    if latest_date:
        payload["latest_date"] = latest_date
    if groups is not None:
        payload["groups"] = groups
    return jsonify(payload)


@app.route("/api/resultados/actualizar-ahora", methods=["POST"])
def api_actualizar_resultados_ahora():
    data = request.get_json(silent=True) or {}
    country = (data.get("country") or request.form.get("country") or "").strip()
    state = (data.get("state") or request.form.get("state") or "").strip()
    lottery = (data.get("lottery") or request.form.get("lottery") or "").strip()

    result = refresh_lottery_results_now(country, state, lottery)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.route("/api/prediction")
def api_prediction():
    lottery_id = request.args.get("lottery_id", type=int)
    draw_name = request.args.get("draw_name", "").strip()
    if not lottery_id or not draw_name:
        return jsonify({"ok": False, "message": "lottery_id y draw_name son requeridos"})
    lottery = get_lottery(lottery_id)
    result = generar_jugada_inteligente(lottery_id, draw_name)
    if not result.get("ok"):
        return jsonify(result)

    draws = get_draw_times(lottery_id, active_only=True)
    draw_time = next((d.get("draw_time") for d in draws if d["draw_name"] == draw_name), "")
    stats = analizar_loteria_por_tanda(lottery_id, draw_name)
    if stats and stats.get("ok"):
        result["hot_numbers"] = stats.get("hot_numbers", [])[:5]
        result["cold_numbers"] = stats.get("cold_numbers", [])[:5]
        result["overdue_numbers"] = stats.get("overdue_numbers", [])[:5]
        result["hot_numbers_detail"] = stats.get("hot_numbers_detail", [])
        result["cold_numbers_detail"] = stats.get("cold_numbers_detail", [])
        result["overdue_numbers_detail"] = stats.get("overdue_numbers_detail", [])
        result["analysis_window"] = stats.get("analysis_window", 25)
        result["total_results"] = stats.get("total_results", 0)

    if lottery:
        result["schedule_label"] = _build_schedule_label(lottery, draw_name, draw_time)
        result["draw_time"] = draw_time
        result["time_display"] = _format_time_12h(draw_time)
        if lottery.get("country") == "RD":
            labels = {"mañana": "Mañana", "tarde": "Tarde", "tardía": "Tardía", "noche": "Noche"}
            result["draw_display"] = labels.get(draw_name, draw_name.capitalize())
        else:
            result["draw_display"] = draw_name

    return jsonify(result)


@app.route("/api/analysis")
def api_analysis():
    lottery_id = request.args.get("lottery_id", type=int)
    draw_name = request.args.get("draw_name", "").strip()
    if not lottery_id or not draw_name:
        return jsonify({"ok": False, "message": "lottery_id y draw_name son requeridos"})
    result = analizar_loteria_por_tanda(lottery_id, draw_name)
    if result and result.get("ok"):
        for key in ("_all_nums", "_freq", "_config"):
            result.pop(key, None)
    return jsonify(result or {"ok": False, "message": "Error en análisis"})


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


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
