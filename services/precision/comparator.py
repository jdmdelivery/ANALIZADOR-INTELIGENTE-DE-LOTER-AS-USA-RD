"""Comparación recomendación vs resultado oficial — por familia de juego."""
from __future__ import annotations

from collections import Counter

from models import parse_numbers


def _box_hits(predicted: list[str], actual: list[str]) -> int:
    if not predicted or not actual:
        return 0
    return sum((Counter(predicted) & Counter(actual)).values())


def _positional_hits(predicted: list[str], actual: list[str]) -> int:
    return sum(1 for i, n in enumerate(predicted) if i < len(actual) and n == actual[i])


def _set_hits(predicted: list[str], actual: list[str]) -> int:
    return len(set(predicted) & set(actual))


def _status_from_pct(pct: float, *, exact_order: bool = False, full_exact: bool = False) -> str:
    from services.precision.constants import STATUS_BAD, STATUS_EXCELLENT, STATUS_GOOD, STATUS_REGULAR

    if full_exact or pct >= 100:
        return STATUS_EXCELLENT
    if pct >= 80:
        return STATUS_EXCELLENT
    if pct >= 60:
        return STATUS_GOOD
    if pct >= 35:
        return STATUS_REGULAR
    return STATUS_BAD


def compare_recommendation(
    predicted: list[str],
    actual: list[str],
    *,
    predicted_bonus: list[str] | None = None,
    actual_bonus: list[str] | None = None,
    game_family: str = "quiniela_rd",
) -> dict:
    """
    Compara jugada recomendada con resultado oficial.
    Devuelve métricas, desglose y texto para UI.
    """
    predicted = [str(n) for n in (predicted or [])]
    actual = [str(n) for n in (actual or [])]
    predicted_bonus = [str(n) for n in (predicted_bonus or [])]
    actual_bonus = [str(n) for n in (actual_bonus or [])]

    family = (game_family or "quiniela_rd").lower()
    n_pred = max(len(predicted), 1)

    exact_set = _set_hits(predicted, actual)
    position_hits = _positional_hits(predicted, actual)
    box_hits = _box_hits(predicted, actual)
    partial_hits = exact_set
    bonus_hits = len(set(predicted_bonus) & set(actual_bonus)) if predicted_bonus and actual_bonus else 0

    exact_order = position_hits == len(predicted) and len(predicted) == len(actual) and predicted == actual
    hit_percentage = round((position_hits / n_pred) * 100, 1)

    detail: dict = {
        "game_family": family,
        "predicted": predicted,
        "actual": actual,
        "predicted_bonus": predicted_bonus,
        "actual_bonus": actual_bonus,
        "lines": [],
    }

    if family == "quiniela_rd":
        detail.update(_quiniela_detail(predicted, actual, position_hits))
        hit_percentage = detail.get("hit_percentage", hit_percentage)
    elif family == "pick":
        detail.update(_pick_detail(predicted, actual, position_hits, box_hits, bonus_hits))
        hit_percentage = detail.get("hit_percentage", hit_percentage)
        exact_order = detail.get("exact_straight", False)
    elif family == "power_mega":
        main_pred = predicted
        main_act = actual
        main_pos = _positional_hits(main_pred, main_act)
        main_set = _set_hits(main_pred, main_act)
        detail.update({
            "main_balls": {
                "predicted": main_pred,
                "actual": main_act,
                "position_hits": main_pos,
                "set_hits": main_set,
            },
            "special_ball": {
                "predicted": predicted_bonus,
                "actual": actual_bonus,
                "hit": bonus_hits > 0,
            },
            "lines": _power_lines(main_pred, main_act, main_pos, predicted_bonus, actual_bonus, bonus_hits),
        })
        main_pct = (main_set / max(len(main_pred), 1)) * 100
        bonus_pct = 100 if bonus_hits else 0
        hit_percentage = round((main_pct * 0.85) + (bonus_pct * 0.15), 1)
    elif family in ("lotto", "kino"):
        detail["lines"] = [
            f"Coincidencias: {exact_set} de {len(predicted)} números",
            f"Aciertos por posición (si aplica): {position_hits}",
        ]
        hit_percentage = round((exact_set / n_pred) * 100, 1)
    else:
        detail["lines"] = [f"Coincidencias: {exact_set}/{len(predicted)}"]

    achieved_score = round(hit_percentage, 1)
    status = _status_from_pct(hit_percentage, full_exact=exact_order)

    return {
        "exact_hits": exact_set,
        "position_hits": position_hits,
        "box_hits": box_hits,
        "partial_hits": partial_hits,
        "bonus_hits": bonus_hits,
        "hit_percentage": hit_percentage,
        "achieved_score": achieved_score,
        "exact_straight": exact_order,
        "status": status,
        "detail": detail,
        "compare_summary": _build_summary(detail, hit_percentage, status),
    }


def _quiniela_detail(predicted: list[str], actual: list[str], position_hits: int) -> dict:
    labels = ("primera", "segunda", "tercera")
    pos_results = []
    lines = []
    for i, label in enumerate(labels):
        hit = i < len(predicted) and i < len(actual) and predicted[i] == actual[i]
        pos_results.append({"position": i + 1, "label": label, "hit": hit, "predicted": predicted[i] if i < len(predicted) else None, "actual": actual[i] if i < len(actual) else None})
        icon = "✅" if hit else "❌"
        name = label.capitalize()
        lines.append(f"{icon} {name} {'acertada' if hit else 'fallida'}")

    set_hits = _set_hits(predicted, actual)
    double_hit = set_hits >= 2
    triple_hit = set_hits >= 3 and len(predicted) >= 3
    if double_hit:
        lines.append("✅ Doble (2+ números en el sorteo)")
    if triple_hit:
        lines.append("🎯 Triple (los 3 números en el sorteo)")

    n = max(len(predicted), 1)
    pct = round((position_hits / n) * 100, 1)
    lines.append(f"🎯 Precisión {pct}%")

    return {
        "position_results": pos_results,
        "double_hit": double_hit,
        "triple_hit": triple_hit,
        "hit_percentage": pct,
        "lines": lines,
    }


def _pick_detail(
    predicted: list[str],
    actual: list[str],
    position_hits: int,
    box_hits: int,
    bonus_hits: int,
) -> dict:
    exact_straight = predicted == actual and len(predicted) == len(actual)
    box_full = box_hits == len(predicted) and len(predicted) == len(actual)
    lines = [
        f"{'✅' if exact_straight else '❌'} Acierto exacto (straight)",
        f"{'✅' if box_full else '❌'} Box ({box_hits}/{len(predicted)} dígitos)",
        f"{'✅' if bonus_hits else '❌'} Fireball / bonus",
        f"Posición correcta: {position_hits}/{len(predicted)} dígitos",
        f"Dígitos acertados (box): {box_hits}",
    ]
    if exact_straight:
        pct = 100.0
    elif box_full:
        pct = 90.0
    else:
        pct = round((position_hits / max(len(predicted), 1)) * 100, 1)
    return {
        "exact_straight": exact_straight,
        "box_full": box_full,
        "fireball_hit": bonus_hits > 0,
        "digit_hits": box_hits,
        "hit_percentage": pct,
        "lines": lines,
    }


def _power_lines(
    main_pred: list[str],
    main_act: list[str],
    main_pos: int,
    pred_bonus: list[str],
    act_bonus: list[str],
    bonus_hits: int,
) -> list[str]:
    lines = [f"Bolas principales: {main_pos}/{len(main_pred)} por posición, {_set_hits(main_pred, main_act)} en conjunto"]
    if pred_bonus:
        lines.append(f"{'✅' if bonus_hits else '❌'} Bola especial: predicho {pred_bonus[0] if pred_bonus else '—'}, salió {act_bonus[0] if act_bonus else '—'}")
    return lines


def _build_summary(detail: dict, pct: float, status: str) -> str:
    from services.precision.constants import STATUS_ICONS, STATUS_LABELS

    lines = detail.get("lines") or []
    icon = STATUS_ICONS.get(status, "")
    label = STATUS_LABELS.get(status, status)
    head = f"{icon} {label} — Precisión {pct}%"
    return head + ("\n" + "\n".join(lines) if lines else "")


def parse_result_row(row: dict) -> tuple[list[str], list[str]]:
    """Extrae main y bonus de una fila lottery_results."""
    main = parse_numbers(row.get("main_numbers") or row.get("numbers"))
    bonus: list[str] = []
    if row.get("bonus_numbers"):
        bonus = parse_numbers(row["bonus_numbers"])
    elif row.get("bonus_number"):
        bonus = parse_numbers(row["bonus_number"])
    elif row.get("fireball_number"):
        bonus = [str(row["fireball_number"])]
    return main, bonus
