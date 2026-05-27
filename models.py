import sqlite3
import json
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

from werkzeug.security import check_password_hash, generate_password_hash

DATABASE = os.environ.get("DATABASE_PATH", "lottery.db")

INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "jdmcashnow")
# En producción definir INITIAL_ADMIN_PASSWORD en variables de entorno
INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "")

DISCLAIMER = (
    "La lotería es un juego de azar. "
    "Esta herramienta solo ofrece análisis estadístico y no garantiza premios."
)

MIN_RESULTS_FOR_ANALYSIS = 10


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sync_lottery_draw_schedules(conn):
    """Alinea draw_times en DB con LOTTERY_SCHEDULES (horarios reales por lotería)."""
    from lottery_schedules import (
        get_lottery_schedule,
        resolve_schedule_key,
        slot_draw_name,
        time_12h_to_24h,
    )

    rows = conn.execute(
        "SELECT id, name FROM lotteries WHERE country = 'RD'"
    ).fetchall()
    for lot in rows:
        if not resolve_schedule_key(lot["name"]):
            continue
        schedule = get_lottery_schedule(lot["name"])
        if not schedule:
            continue
        allowed = set()
        for slot in schedule:
            draw_name = slot_draw_name(slot)
            allowed.add(draw_name)
            t24 = time_12h_to_24h(slot["time"])
            existing = conn.execute(
                "SELECT id FROM draw_times WHERE lottery_id = ? AND draw_name = ?",
                (lot["id"], draw_name),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE draw_times SET draw_time = ?, active = 1 WHERE id = ?",
                    (t24, existing["id"]),
                )
            else:
                conn.execute(
                    """INSERT INTO draw_times
                       (lottery_id, draw_name, draw_time, timezone, active)
                       VALUES (?, ?, ?, 'America/Santo_Domingo', 1)""",
                    (lot["id"], draw_name, t24),
                )
        for d in conn.execute(
            "SELECT id, draw_name FROM draw_times WHERE lottery_id = ?",
            (lot["id"],),
        ).fetchall():
            if d["draw_name"] not in allowed:
                conn.execute(
                    "UPDATE draw_times SET active = 0 WHERE id = ?",
                    (d["id"],),
                )


def migrate_db():
    """Migraciones incrementales sobre DB existente."""
    conn = get_connection()
    try:
        conn.execute("""
            DELETE FROM lottery_results
            WHERE id NOT IN (
                SELECT MAX(id) FROM lottery_results
                GROUP BY lottery_id, draw_date, draw_name
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_results_lottery_date_draw
            ON lottery_results (lottery_id, draw_date, draw_name)
        """)
        for col in ("main_numbers", "bonus_numbers", "bonus_label", "game_name"):
            try:
                conn.execute(f"ALTER TABLE lottery_results ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        _sync_lottery_draw_schedules(conn)
        # Lucky Day Lotto: asegurar tanda Midday en DB existente
        ld = conn.execute(
            "SELECT id FROM lotteries WHERE name = 'Lucky Day Lotto' AND country = 'USA'"
        ).fetchone()
        if ld:
            has_midday = conn.execute(
                "SELECT id FROM draw_times WHERE lottery_id = ? AND draw_name = 'Midday'",
                (ld["id"],),
            ).fetchone()
            if not has_midday:
                conn.execute(
                    """INSERT INTO draw_times (lottery_id, draw_name, draw_time, timezone, active)
                       VALUES (?, 'Midday', '12:40', 'America/Chicago', 1)""",
                    (ld["id"],),
                )
        for col_sql in (
            "ALTER TABLE lottery_results ADD COLUMN estado TEXT DEFAULT 'publicado'",
            "ALTER TABLE lottery_results ADD COLUMN fuente TEXT",
            "ALTER TABLE lottery_results ADD COLUMN updated_at TEXT",
        ):
            try:
                conn.execute(col_sql)
            except sqlite3.OperationalError:
                pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leidsa_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ok INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                error TEXT,
                imported INTEGER DEFAULT 0,
                updated INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leidsa_fetch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                status_code INTEGER,
                parser TEXT,
                method TEXT,
                results_found INTEGER DEFAULT 0,
                html_length INTEGER DEFAULT 0,
                error TEXT,
                blocking_type TEXT,
                api_urls TEXT,
                ok INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                nombre TEXT,
                email TEXT,
                role TEXT NOT NULL DEFAULT 'usuario',
                is_active INTEGER NOT NULL DEFAULT 1,
                expires_at TEXT,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                last_login TEXT
            )
        """)
        seed_rd_conectate_lotteries(conn)
        seed_leidsa_lotteries(conn)
        _sync_lottery_draw_schedules(conn)
        conn.commit()
    finally:
        conn.close()


def seed_rd_conectate_lotteries(conn=None):
    """Crea/activa loterías RD estándar (Conectate + Florida/King/NY)."""
    from lottery_schedules import RD_CONECTATE_LOTTERIES

    def _run(c):
        for cfg in RD_CONECTATE_LOTTERIES:
            name = cfg["name"]
            slug = cfg["type"]
            state = cfg.get("state") or ""
            aliases = tuple(cfg.get("aliases") or ())
            names = (name,) + aliases
            placeholders = ",".join("?" * len(names))
            row = c.execute(
                f"""SELECT id FROM lotteries
                    WHERE country = 'RD' AND (type = ? OR name IN ({placeholders}))""",
                (slug, *names),
            ).fetchone()
            if not row:
                c.execute(
                    "INSERT INTO lotteries (country, state, name, type, active) VALUES (?,?,?,?,1)",
                    ("RD", state, name, slug),
                )
            else:
                c.execute(
                    "UPDATE lotteries SET active = 1, state = ?, type = ? WHERE id = ?",
                    (state, slug, row["id"]),
                )

    if conn is not None:
        _run(conn)
    else:
        with get_db() as c:
            _run(c)


def seed_leidsa_lotteries(conn=None):
    """Crea loterías LEIDSA por juego (separadas de Leidsa/Conectate)."""
    from services.leidsa_config import LEIDSA_GAMES

    def _run(c):
        old = c.execute(
            "SELECT id FROM lotteries WHERE name = 'Leidsa' AND country = 'RD'"
        ).fetchone()
        if old:
            c.execute("UPDATE lotteries SET active = 0 WHERE id = ?", (old["id"],))
        # Migrar slug antiguo pega3_mas → leidsa_pega3
        old_pega = c.execute(
            "SELECT id FROM lotteries WHERE type = 'leidsa_pega3_mas' AND country = 'RD'"
        ).fetchone()
        if old_pega:
            c.execute(
                "UPDATE lotteries SET type = 'leidsa_pega3', active = 1 WHERE id = ?",
                (old_pega["id"],),
            )

        for slug, cfg in LEIDSA_GAMES.items():
            row = c.execute(
                "SELECT id FROM lotteries WHERE type = ? AND country = 'RD'",
                (slug,),
            ).fetchone()
            if not row:
                c.execute(
                    "INSERT INTO lotteries (country, state, name, type, active) VALUES (?,?,?,?,1)",
                    ("RD", "LEIDSA", cfg["lottery_name"], slug),
                )
                lot_id = c.execute("SELECT last_insert_rowid()").fetchone()[0]
            else:
                lot_id = row["id"]
                c.execute(
                    "UPDATE lotteries SET name = ?, active = 1 WHERE id = ?",
                    (cfg["lottery_name"], lot_id),
                )
            for slot in cfg["draws"]:
                ex = c.execute(
                    "SELECT id FROM draw_times WHERE lottery_id = ? AND draw_name = ?",
                    (lot_id, slot["draw_name"]),
                ).fetchone()
                if ex:
                    c.execute(
                        "UPDATE draw_times SET draw_time = ?, timezone = ?, active = 1 WHERE id = ?",
                        (slot["time_24h"], "America/Santo_Domingo", ex["id"]),
                    )
                else:
                    c.execute(
                        """INSERT INTO draw_times
                           (lottery_id, draw_name, draw_time, timezone, active)
                           VALUES (?, ?, ?, 'America/Santo_Domingo', 1)""",
                        (lot_id, slot["draw_name"], slot["time_24h"]),
                    )

    if conn is not None:
        _run(conn)
    else:
        with get_db() as c:
            _run(c)


def get_lottery_by_slug(slug):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM lotteries WHERE type = ? AND country = 'RD'",
            (slug,),
        ).fetchone()
        return row_to_dict(row)


def log_leidsa_sync(ok, message="", error=None, imported=0, updated=0):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO leidsa_sync_log (ok, message, error, imported, updated)
               VALUES (?,?,?,?,?)""",
            (1 if ok else 0, message, error, imported, updated),
        )


def get_last_leidsa_sync():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM leidsa_sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        d = row_to_dict(row)
        if d:
            d["ok"] = bool(d.get("ok"))
        return d


def log_leidsa_fetch(
    ok,
    status_code=None,
    parser="",
    method="",
    results_found=0,
    html_length=0,
    error=None,
    blocking_type="",
    api_urls=None,
):
    urls_json = json.dumps(api_urls or []) if api_urls else "[]"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO leidsa_fetch_logs
               (ok, status_code, parser, method, results_found, html_length,
                error, blocking_type, api_urls)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                1 if ok else 0,
                status_code,
                parser or "",
                method or "",
                results_found,
                html_length,
                error,
                blocking_type or "",
                urls_json,
            ),
        )


def get_last_leidsa_fetch():
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM leidsa_fetch_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        d = row_to_dict(row)
        if not d:
            return None
        d["ok"] = bool(d.get("ok"))
        try:
            d["api_urls"] = json.loads(d.get("api_urls") or "[]")
        except json.JSONDecodeError:
            d["api_urls"] = []
        return d


def get_leidsa_results_for_date(fecha_rd):
    from services.leidsa_config import LEIDSA_SLUGS

    slugs = list(LEIDSA_SLUGS) + ["leidsa_pega3_mas"]
    if not slugs:
        return []
    placeholders = ",".join("?" * len(slugs))
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT r.*, l.name AS lottery_display, l.type AS lottery_slug
                FROM lottery_results r
                JOIN lotteries l ON l.id = r.lottery_id
                WHERE l.type IN ({placeholders}) AND r.draw_date = ?
                ORDER BY l.name, r.draw_name""",
            (*slugs, fecha_rd),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            d["numeros_list"] = parse_numbers(d.get("numbers"))
            out.append(d)
        return out


def get_leidsa_history_from_db(limit_days=30):
    """Historial LEIDSA guardado en lottery_results."""
    from services.leidsa_config import LEIDSA_SLUGS

    slugs = list(LEIDSA_SLUGS) + ["leidsa_pega3_mas"]
    placeholders = ",".join("?" * len(slugs))
    cutoff = (datetime.now() - timedelta(days=limit_days)).strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT r.*, l.name AS lottery_display, l.type AS lottery_slug
                FROM lottery_results r
                JOIN lotteries l ON l.id = r.lottery_id
                WHERE l.type IN ({placeholders})
                  AND r.draw_date >= ?
                ORDER BY r.draw_date DESC, l.name, r.draw_name""",
            (*slugs, cutoff),
        ).fetchall()
        out = []
        for r in rows:
            d = row_to_dict(r)
            d["numeros_list"] = parse_numbers(d.get("numbers"))
            d["time_display"] = d.get("draw_time", "")
            out.append(d)
        return out


def seed_initial_admin():
    """Crea admin inicial si no existe (contraseña vía INITIAL_ADMIN_PASSWORD)."""
    password = (os.environ.get("INITIAL_ADMIN_PASSWORD") or INITIAL_ADMIN_PASSWORD or "").strip()
    if not password:
        from config_app import IS_PRODUCTION
        if IS_PRODUCTION:
            print("[WARN] INITIAL_ADMIN_PASSWORD no definido; no se crea admin automático.")
            return False
        password = "Moose555@"  # solo desarrollo local sin .env

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (INITIAL_ADMIN_USERNAME,),
        ).fetchone()
        if existing:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """INSERT INTO users
               (username, password_hash, nombre, email, role, is_active,
                expires_at, must_change_password, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                INITIAL_ADMIN_USERNAME,
                generate_password_hash(password),
                "Administrador",
                "",
                "admin",
                1,
                None,
                0,
                now,
                now,
            ),
        )
    print("[OK] Admin inicial creado:")
    print(INITIAL_ADMIN_USERNAME)
    return True


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS lotteries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                country TEXT NOT NULL,
                state TEXT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS draw_times (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                draw_name TEXT NOT NULL,
                draw_time TEXT,
                timezone TEXT DEFAULT 'America/New_York',
                active INTEGER DEFAULT 1,
                FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS lottery_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                draw_name TEXT NOT NULL,
                draw_time TEXT,
                draw_date TEXT NOT NULL,
                numbers TEXT NOT NULL,
                bonus_number TEXT,
                fireball_number TEXT,
                source_url TEXT,
                confirmed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lottery_id INTEGER NOT NULL,
                draw_name TEXT NOT NULL,
                generated_numbers TEXT NOT NULL,
                analysis_text TEXT,
                confidence_level TEXT,
                score REAL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (lottery_id) REFERENCES lotteries(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS api_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL UNIQUE,
                api_url TEXT,
                api_key TEXT,
                active INTEGER DEFAULT 0,
                last_sync TEXT
            );
        """)
    migrate_db()
    seed_initial_admin()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def parse_numbers(numbers_str):
    if not numbers_str:
        return []
    try:
        parsed = json.loads(numbers_str)
        if isinstance(parsed, list):
            return [str(n) for n in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [n.strip() for n in str(numbers_str).replace("|", ",").split(",") if n.strip()]


def format_numbers(numbers_list):
    return json.dumps([str(n) for n in numbers_list])


# --- Lottery CRUD ---

def get_all_lotteries(active_only=False):
    with get_db() as conn:
        q = "SELECT * FROM lotteries"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY country, state, name"
        rows = conn.execute(q).fetchall()
        return [row_to_dict(r) for r in rows]


def get_lottery(lottery_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM lotteries WHERE id = ?", (lottery_id,)).fetchone()
        return row_to_dict(row)


def create_lottery(country, state, name, lottery_type, active=1):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO lotteries (country, state, name, type, active) VALUES (?, ?, ?, ?, ?)",
            (country, state, name, lottery_type, active),
        )
        return cur.lastrowid


def update_lottery(lottery_id, country, state, name, lottery_type, active):
    with get_db() as conn:
        conn.execute(
            "UPDATE lotteries SET country=?, state=?, name=?, type=?, active=? WHERE id=?",
            (country, state, name, lottery_type, active, lottery_id),
        )


def toggle_lottery(lottery_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE lotteries SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",
            (lottery_id,),
        )


# --- Draw Times CRUD ---

def get_draw_times(lottery_id, active_only=False):
    with get_db() as conn:
        q = "SELECT * FROM draw_times WHERE lottery_id = ?"
        params = [lottery_id]
        if active_only:
            q += " AND active = 1"
        q += " ORDER BY draw_name"
        rows = conn.execute(q, params).fetchall()
        return [row_to_dict(r) for r in rows]


def create_draw_time(lottery_id, draw_name, draw_time, timezone, active=1):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO draw_times (lottery_id, draw_name, draw_time, timezone, active) VALUES (?,?,?,?,?)",
            (lottery_id, draw_name, draw_time, timezone, active),
        )
        return cur.lastrowid


def update_draw_time(draw_id, draw_name, draw_time, timezone, active):
    with get_db() as conn:
        conn.execute(
            "UPDATE draw_times SET draw_name=?, draw_time=?, timezone=?, active=? WHERE id=?",
            (draw_name, draw_time, timezone, active, draw_id),
        )


def toggle_draw_time(draw_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE draw_times SET active = CASE WHEN active=1 THEN 0 ELSE 1 END WHERE id=?",
            (draw_id,),
        )


def delete_draw_time(draw_id):
    with get_db() as conn:
        conn.execute("DELETE FROM draw_times WHERE id=?", (draw_id,))


# --- Results CRUD ---

def get_results(lottery_id=None, draw_name=None, limit=50):
    with get_db() as conn:
        q = "SELECT * FROM lottery_results WHERE 1=1"
        params = []
        if lottery_id:
            q += " AND lottery_id = ?"
            params.append(lottery_id)
        if draw_name:
            q += " AND draw_name = ?"
            params.append(draw_name)
        q += " ORDER BY draw_date DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [row_to_dict(r) for r in rows]


RD_DRAW_ORDER = {"mañana": 1, "tarde": 2, "tardía": 3, "noche": 4}


def _draw_sort_key(draw_name):
    return RD_DRAW_ORDER.get(draw_name or "", 99)


def get_max_draw_date(lottery_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT MAX(draw_date) AS max_date FROM lottery_results WHERE lottery_id = ?",
            (lottery_id,),
        ).fetchone()
        return row["max_date"] if row and row["max_date"] else None


def count_results_for_lottery(lottery_id, draw_name=None):
    """Cantidad de sorteos guardados en BD para una lotería."""
    with get_db() as conn:
        if draw_name:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id = ? AND draw_name = ?",
                (lottery_id, draw_name),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM lottery_results WHERE lottery_id = ?",
                (lottery_id,),
            ).fetchone()
        return int(row["c"]) if row else 0


def get_results_for_latest_date(lottery_id, draw_name=None):
    with get_db() as conn:
        if draw_name:
            row = conn.execute(
                """SELECT MAX(draw_date) AS max_date FROM lottery_results
                   WHERE lottery_id = ? AND draw_name = ?""",
                (lottery_id, draw_name),
            ).fetchone()
            max_date = row["max_date"] if row else None
        else:
            row = conn.execute(
                "SELECT MAX(draw_date) AS max_date FROM lottery_results WHERE lottery_id = ?",
                (lottery_id,),
            ).fetchone()
            max_date = row["max_date"] if row else None
    if not max_date:
        return [], None
    with get_db() as conn:
        q = "SELECT * FROM lottery_results WHERE lottery_id = ? AND draw_date = ?"
        params = [lottery_id, max_date]
        if draw_name:
            q += " AND draw_name = ?"
            params.append(draw_name)
        rows = conn.execute(q, params).fetchall()
        results = [row_to_dict(r) for r in rows]
        results.sort(key=lambda r: _draw_sort_key(r.get("draw_name")))
        return results, max_date


def get_results_grouped_by_date(lottery_id, limit_days=30, draw_name=None):
    """limit_days=0 o None → sin filtro de fecha (todo el historial guardado)."""
    with get_db() as conn:
        q = """SELECT DISTINCT draw_date FROM lottery_results
               WHERE lottery_id = ?"""
        params: list = [lottery_id]
        if draw_name:
            q += " AND draw_name = ?"
            params.append(draw_name)
        if limit_days and int(limit_days) > 0:
            cutoff = (datetime.now() - timedelta(days=int(limit_days))).strftime("%Y-%m-%d")
            q += " AND draw_date >= ?"
            params.append(cutoff)
        q += " ORDER BY draw_date DESC"
        if limit_days and int(limit_days) > 0:
            q += " LIMIT ?"
            params.append(int(limit_days) * 4)
        date_rows = conn.execute(q, params).fetchall()
        groups = []
        for dr in date_rows:
            draw_date = dr["draw_date"]
            rq = """SELECT * FROM lottery_results
                    WHERE lottery_id = ? AND draw_date = ?"""
            rparams = [lottery_id, draw_date]
            if draw_name:
                rq += " AND draw_name = ?"
                rparams.append(draw_name)
            rows = conn.execute(rq, rparams).fetchall()
            results = [row_to_dict(r) for r in rows]
            results.sort(key=lambda r: _draw_sort_key(r.get("draw_name")))
            groups.append({"draw_date": draw_date, "results": results})
        return groups


def get_results_history(lottery_id, draw_name=None, days=30, limit=500):
    """Historial por lotería (y tanda). days=0 → sin filtro de fecha."""
    with get_db() as conn:
        q = "SELECT * FROM lottery_results WHERE lottery_id = ?"
        params: list = [lottery_id]
        if days and int(days) > 0:
            cutoff = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
            q += " AND draw_date >= ?"
            params.append(cutoff)
        if draw_name:
            q += " AND draw_name = ?"
            params.append(draw_name)
        q += " ORDER BY draw_date DESC, draw_name DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [row_to_dict(r) for r in rows]


def count_results_by_lottery():
    with get_db() as conn:
        rows = conn.execute(
            """SELECT l.name, l.country, COUNT(r.id) AS total,
                      MAX(r.draw_date) AS last_date
               FROM lotteries l
               LEFT JOIN lottery_results r ON r.lottery_id = l.id
               GROUP BY l.id
               ORDER BY total DESC, l.name"""
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_recent_results_rows(limit=20):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT r.*, l.name AS lottery_name, l.country
               FROM lottery_results r
               JOIN lotteries l ON l.id = r.lottery_id
               ORDER BY r.draw_date DESC, r.id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def get_results_for_analysis(lottery_id, draw_name, limit=None):
    with get_db() as conn:
        sql = """SELECT * FROM lottery_results
               WHERE lottery_id = ? AND draw_name = ?
               ORDER BY draw_date DESC, id DESC"""
        params: list = [lottery_id, draw_name]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = conn.execute(sql, params).fetchall()
        return [row_to_dict(r) for r in rows]


def enrich_result_row(row, lottery=None):
    """Normaliza main/bonus numbers para API y UI."""
    if not row:
        return row
    main = parse_numbers(row.get("main_numbers") or row.get("numbers"))
    bonus = parse_numbers(row.get("bonus_numbers") or "")
    if not bonus and row.get("bonus_number"):
        bonus = [str(row["bonus_number"])]
    if not bonus and row.get("fireball_number"):
        bonus = [str(row["fireball_number"])]

    bonus_label = row.get("bonus_label")
    if not bonus_label and lottery and bonus:
        labels = {
            "powerball": "Powerball",
            "mega_millions": "Mega Ball",
            "lotto": "Extra Shot",
            "pick3": "Fireball",
            "pick4": "Fireball",
        }
        bonus_label = labels.get(lottery.get("type"))

    row["main_numbers"] = main
    row["bonus_numbers"] = bonus
    row["numbers"] = main
    row["bonus_label"] = bonus_label
    return row


def create_result(lottery_id, draw_name, draw_time, draw_date, numbers,
                  bonus_number=None, fireball_number=None, source_url=None, confirmed=0,
                  main_numbers=None, bonus_numbers=None, bonus_label=None, game_name=None):
    result_id, _ = upsert_result(
        lottery_id, draw_name, draw_time, draw_date, numbers,
        bonus_number=bonus_number, fireball_number=fireball_number,
        source_url=source_url, confirmed=confirmed,
        main_numbers=main_numbers, bonus_numbers=bonus_numbers,
        bonus_label=bonus_label, game_name=game_name,
    )
    return result_id


def upsert_result(lottery_id, draw_name, draw_time, draw_date, numbers,
                  bonus_number=None, fireball_number=None, source_url=None, confirmed=0,
                  main_numbers=None, bonus_numbers=None, bonus_label=None, game_name=None,
                  estado="publicado", fuente=None):
    """INSERT o UPDATE por (lottery_id, draw_date, draw_name)."""
    if isinstance(numbers, str) and numbers.startswith("["):
        nums = format_numbers(parse_numbers(numbers))
    else:
        nums = format_numbers(parse_numbers(numbers) if not isinstance(numbers, list) else numbers)

    main_json = main_numbers if main_numbers else nums
    if isinstance(main_json, list):
        main_json = format_numbers(main_json)
    bonus_json = bonus_numbers
    if isinstance(bonus_json, list):
        bonus_json = format_numbers(bonus_json)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    src = fuente or source_url or ""
    with get_db() as conn:
        existing = conn.execute(
            """SELECT id FROM lottery_results
               WHERE lottery_id = ? AND draw_date = ? AND draw_name = ?""",
            (lottery_id, draw_date, draw_name),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE lottery_results
                   SET draw_time = ?, numbers = ?, bonus_number = ?, fireball_number = ?,
                       source_url = ?, confirmed = ?,
                       main_numbers = ?, bonus_numbers = ?, bonus_label = ?, game_name = ?,
                       estado = ?, fuente = ?, updated_at = ?
                   WHERE id = ?""",
                (draw_time, nums, bonus_number, fireball_number, source_url, confirmed,
                 main_json, bonus_json, bonus_label, game_name, estado, src, now,
                 existing["id"]),
            )
            return existing["id"], "updated"
        cur = conn.execute(
            """INSERT INTO lottery_results
               (lottery_id, draw_name, draw_time, draw_date, numbers,
                bonus_number, fireball_number, source_url, confirmed,
                main_numbers, bonus_numbers, bonus_label, game_name,
                estado, fuente, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lottery_id, draw_name, draw_time, draw_date, nums,
             bonus_number, fireball_number, source_url, confirmed,
             main_json, bonus_json, bonus_label, game_name, estado, src, now),
        )
        return cur.lastrowid, "inserted"


def delete_result(result_id):
    with get_db() as conn:
        conn.execute("DELETE FROM lottery_results WHERE id=?", (result_id,))


def toggle_result_confirmed(result_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE lottery_results SET confirmed = CASE WHEN confirmed=1 THEN 0 ELSE 1 END WHERE id=?",
            (result_id,),
        )


# --- Predictions CRUD ---

def create_prediction(lottery_id, draw_name, generated_numbers, analysis_text,
                      confidence_level, score):
    with get_db() as conn:
        nums = format_numbers(generated_numbers)
        cur = conn.execute(
            """INSERT INTO predictions
               (lottery_id, draw_name, generated_numbers, analysis_text,
                confidence_level, score)
               VALUES (?,?,?,?,?,?)""",
            (lottery_id, draw_name, nums, analysis_text, confidence_level, score),
        )
        return cur.lastrowid


def get_predictions(lottery_id=None, limit=50):
    with get_db() as conn:
        q = """SELECT p.*, l.name as lottery_name, l.country, l.state
               FROM predictions p
               JOIN lotteries l ON l.id = p.lottery_id
               WHERE 1=1"""
        params = []
        if lottery_id:
            q += " AND p.lottery_id = ?"
            params.append(lottery_id)
        q += " ORDER BY p.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        results = []
        for r in rows:
            d = row_to_dict(r)
            d["generated_numbers"] = parse_numbers(d["generated_numbers"])
            results.append(d)
        return results


# --- API Config ---

def get_api_configs():
    with get_db() as conn:
        rows = conn.execute("SELECT id, source_name, api_url, active, last_sync FROM api_config").fetchall()
        return [row_to_dict(r) for r in rows]


def upsert_api_config(source_name, api_url, api_key, active=0):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM api_config WHERE source_name = ?", (source_name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE api_config SET api_url=?, api_key=?, active=? WHERE source_name=?",
                (api_url, api_key, active, source_name),
            )
        else:
            conn.execute(
                "INSERT INTO api_config (source_name, api_url, api_key, active) VALUES (?,?,?,?)",
                (source_name, api_url, api_key, active),
            )


LOTTERY_CONFIG = {
    "pick3": {
        "count": 3,
        "min": 0,
        "max": 9,
        "allow_repeat": True,
        "max_repeat_per_number": 2,
        "min_unique": 2,
        "pad": 1,
        "bonus_min": 0,
        "bonus_max": 9,
    },
    "pick4": {
        "count": 4,
        "min": 0,
        "max": 9,
        "allow_repeat": True,
        "max_repeat_per_number": 2,
        "min_unique": 3,
        "pick4_strict": True,
        "pad": 1,
        "bonus_min": 0,
        "bonus_max": 9,
    },
    "quiniela": {"count": 3, "min": 0, "max": 99, "allow_repeat": True, "pad": 2},
    "lucky_day": {"count": 5, "min": 1, "max": 45, "allow_repeat": False, "pad": 2},
    "lotto": {"count": 6, "min": 1, "max": 52, "allow_repeat": False, "pad": 2, "bonus_min": 1, "bonus_max": 25},
    "powerball": {"count": 5, "min": 1, "max": 69, "allow_repeat": False, "pad": 2, "bonus_min": 1, "bonus_max": 26},
    "mega_millions": {"count": 5, "min": 1, "max": 70, "allow_repeat": False, "pad": 2, "bonus_min": 1, "bonus_max": 25},
}


def get_lottery_config(lottery_type):
    return LOTTERY_CONFIG.get(lottery_type, LOTTERY_CONFIG["quiniela"])


# --- Users CRUD ---

def get_user_by_id(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row_to_dict(row)


def get_user_by_username(username):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return row_to_dict(row)


def get_all_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY role DESC, username ASC"
        ).fetchall()
        return [row_to_dict(r) for r in rows]


def create_user(username, password, nombre="", email="", role="usuario",
                is_active=1, expires_at=None, must_change_password=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO users
               (username, password_hash, nombre, email, role, is_active,
                expires_at, must_change_password, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                username.strip().lower(),
                generate_password_hash(password),
                nombre.strip(),
                email.strip(),
                role,
                int(is_active),
                expires_at or None,
                int(must_change_password),
                now,
                now,
            ),
        )
        return cur.lastrowid


def update_user(user_id, nombre=None, email=None, role=None, is_active=None,
                expires_at=None, must_change_password=None, clear_expiry=False):
    fields = []
    params = []
    if nombre is not None:
        fields.append("nombre = ?")
        params.append(nombre.strip())
    if email is not None:
        fields.append("email = ?")
        params.append(email.strip())
    if role is not None:
        fields.append("role = ?")
        params.append(role)
    if is_active is not None:
        fields.append("is_active = ?")
        params.append(int(is_active))
    if clear_expiry:
        fields.append("expires_at = ?")
        params.append(None)
    elif expires_at is not None:
        fields.append("expires_at = ?")
        params.append(expires_at or None)
    if must_change_password is not None:
        fields.append("must_change_password = ?")
        params.append(int(must_change_password))
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    params.append(user_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
            params,
        )


def set_user_password(user_id, password, must_change_password=0):
    with get_db() as conn:
        conn.execute(
            """UPDATE users SET password_hash = ?, must_change_password = ?,
               updated_at = ? WHERE id = ?""",
            (
                generate_password_hash(password),
                int(must_change_password),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                user_id,
            ),
        )


def set_user_active(user_id, active):
    update_user(user_id, is_active=1 if active else 0)


def delete_user(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def update_last_login(user_id):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?",
            (now, now, user_id),
        )


def verify_user_password(user_row, password):
    if not user_row:
        return False
    return check_password_hash(user_row["password_hash"], password)
