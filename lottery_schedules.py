"""Horarios oficiales por lotería (fuente única para botones y dropdown)."""

import unicodedata

LOTTERY_SCHEDULES = {
    "Anguila": [
        {"label": "Mañana", "time": "10:00 AM"},
        {"label": "Tarde", "time": "1:00 PM"},
        {"label": "Tardía", "time": "6:00 PM"},
        {"label": "Noche", "time": "9:00 PM"},
    ],
    "Florida": [
        {"label": "Tarde", "time": "1:30 PM"},
        {"label": "Noche", "time": "9:45 PM"},
    ],
    "King Lottery": [
        {"label": "Tarde", "time": "12:30 PM"},
        {"label": "Noche", "time": "7:30 PM"},
    ],
    "La Primera": [
        {"label": "Tarde", "time": "12:00 PM", "draw_name": "mañana"},
        {"label": "Noche", "time": "7:00 PM"},
    ],
    "La Suerte Dominicana": [
        {"label": "Tarde", "time": "12:30 PM"},
        {"label": "Noche", "time": "6:00 PM"},
    ],
    "Leidsa": [
        {"label": "Tarde", "time": "3:55 PM"},
        {"label": "Noche", "time": "8:55 PM"},
    ],
    "Lotedom": [
        {"label": "Tarde", "time": "12:00 PM"},
    ],
    "Loteka": [
        {"label": "Noche", "time": "7:55 PM"},
    ],
    "Lotería Nacional": [
        {"label": "Tarde", "time": "2:30 PM"},
        {"label": "Tardía", "time": "6:00 PM"},
        {"label": "Noche", "time": "9:00 PM"},
    ],
    "New York": [
        {"label": "Tarde", "time": "2:30 PM"},
        {"label": "Noche", "time": "10:30 PM"},
    ],
    "Quiniela Real": [
        {"label": "Tarde", "time": "12:55 PM"},
    ],
}

# Nombres en DB u otras fuentes → clave del mapa
LOTTERY_SCHEDULE_ALIASES = {
    "anguila": "Anguila",
    "suerte dominicana": "La Suerte Dominicana",
    "la suerte dominicana": "La Suerte Dominicana",
    "loteria real": "Quiniela Real",
    "lotería real": "Quiniela Real",
    "quiniela real": "Quiniela Real",
    "loto real": "Quiniela Real",
    "gana mas": "Gana Más",
    "gana más": "Gana Más",
}

LABEL_TO_DRAW_NAME = {
    "mañana": "mañana",
    "manana": "mañana",
    "tarde": "tarde",
    "tardía": "tardía",
    "tardia": "tardía",
    "noche": "noche",
}

DRAW_EMOJI = {
    "mañana": "🌅",
    "tarde": "🌇",
    "tardía": "🎯",
    "noche": "🌙",
}

DRAW_CSS = {
    "mañana": "tanda-manana",
    "tarde": "tanda-tarde",
    "tardía": "tanda-tardia",
    "noche": "tanda-noche",
}


def _norm_name(name):
    if not name:
        return ""
    text = unicodedata.normalize("NFD", str(name).strip())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.casefold()


def resolve_schedule_key(lottery_name):
    if not lottery_name:
        return None
    if lottery_name in LOTTERY_SCHEDULES:
        return lottery_name
    folded = _norm_name(lottery_name)
    if folded in LOTTERY_SCHEDULE_ALIASES:
        return LOTTERY_SCHEDULE_ALIASES[folded]
    for key in LOTTERY_SCHEDULES:
        if _norm_name(key) == folded:
            return key
    return None


def label_to_draw_name(label):
    return LABEL_TO_DRAW_NAME.get((label or "").strip().casefold(), (label or "").strip().lower())


def slot_draw_name(slot):
    return slot.get("draw_name") or label_to_draw_name(slot.get("label", ""))


def time_12h_to_24h(time_12h):
    """'10:00 AM' -> '10:00', '1:30 PM' -> '13:30'."""
    if not time_12h:
        return ""
    raw = str(time_12h).strip().upper()
    try:
        part, meridiem = raw.split()
        h_s, m_s = part.split(":")
        h, m = int(h_s), int(m_s)
        if meridiem == "PM" and h != 12:
            h += 12
        elif meridiem == "AM" and h == 12:
            h = 0
        return f"{h:02d}:{m:02d}"
    except (ValueError, AttributeError):
        return raw


def get_lottery_schedule(lottery_name):
    key = resolve_schedule_key(lottery_name)
    if not key:
        return None
    return LOTTERY_SCHEDULES.get(key)


def get_schedule_slot(lottery_name, draw_name):
    schedule = get_lottery_schedule(lottery_name)
    if not schedule:
        return None
    target = (draw_name or "").casefold()
    for slot in schedule:
        if slot_draw_name(slot).casefold() == target:
            return slot
    return None


def build_draw_buttons(lottery, draw_rows=None):
    """Botones/dropdown para una lotería según LOTTERY_SCHEDULES."""
    schedule = get_lottery_schedule(lottery.get("name", ""))
    if not schedule:
        return None
    draw_map = {}
    if draw_rows:
        draw_map = {d["draw_name"]: d for d in draw_rows}
    buttons = []
    for slot in schedule:
        draw_name = slot_draw_name(slot)
        db_row = draw_map.get(draw_name, {})
        draw_time_24 = db_row.get("draw_time") or time_12h_to_24h(slot["time"])
        buttons.append({
            "draw_name": draw_name,
            "label": slot["label"],
            "time": slot["time"],
            "time_display": slot["time"],
            "draw_time": draw_time_24,
            "emoji": DRAW_EMOJI.get(draw_name, "🎱"),
            "css": DRAW_CSS.get(draw_name, "tanda-default"),
        })
    return buttons


def schedule_draw_order(draw_name):
    order = {"mañana": 1, "tarde": 2, "tardía": 3, "noche": 4}
    return order.get(draw_name or "", 99)
