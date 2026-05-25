import random
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations

from models import (
    DISCLAIMER,
    MIN_RESULTS_FOR_ANALYSIS,
    create_prediction,
    get_all_lotteries,
    get_lottery,
    get_lottery_config,
    get_results_for_analysis,
    parse_numbers,
)


def _normalize_number(n, pad=2):
    try:
        return str(int(n)).zfill(pad)
    except (ValueError, TypeError):
        return str(n).zfill(pad)


def _extract_all_numbers(results):
    all_nums = []
    per_draw = []
    for r in results:
        nums = parse_numbers(r["numbers"])
        per_draw.append(nums)
        all_nums.extend(nums)
    return all_nums, per_draw


def _frequency_counter(numbers):
    return Counter(numbers)


RECENT_WINDOW_DEFAULT = 25
TREND_RECENT_DRAWS = 10
TREND_PREVIOUS_DRAWS = 10
TOP_STAT_COUNT = 5


def _parse_draw_date(date_str):
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _days_between(date_a, date_b):
    da, db = _parse_draw_date(date_a), _parse_draw_date(date_b)
    if not da or not db:
        return None
    return abs((db - da).days)


def _detect_trend(number, recent_draws):
    """📈 tendencia | 📉 caída | ⚠️ sobrecalentado | None"""
    if len(recent_draws) < 6:
        return None, None, None

    recent_10 = recent_draws[:TREND_RECENT_DRAWS]
    older_10 = recent_draws[TREND_RECENT_DRAWS:TREND_RECENT_DRAWS + TREND_PREVIOUS_DRAWS]
    count_recent = sum(1 for d in recent_10 if number in d)
    count_older = sum(1 for d in older_10 if number in d) if older_10 else 0

    last_5 = recent_draws[:5]
    appearances_last_5 = sum(1 for d in last_5 if number in d)
    if appearances_last_5 >= 3 or count_recent >= 5:
        return "overheated", "⚠️", "sobrecalentado"

    if count_recent > count_older + 1:
        return "rising", "📈", "tendencia"
    if count_older > count_recent + 1:
        return "falling", "📉", "caída"
    return None, None, None


def _build_number_profiles(results, per_draw, config, window=RECENT_WINDOW_DEFAULT):
    window = min(window, len(per_draw))
    if window == 0:
        return {}, 0

    pad = config.get("pad", 2)
    universe = [
        _normalize_number(i, pad)
        for i in range(config["min"], config["max"] + 1)
    ]

    recent_results = results[:window]
    recent_draws = per_draw[:window]
    reference_date = recent_results[0].get("draw_date") if recent_results else None

    freq = Counter(n for d in recent_draws for n in d)
    last_seen_draw = {}
    last_seen_date = {}
    for draw_idx, (row, nums) in enumerate(zip(recent_results, recent_draws)):
        for n in nums:
            if n not in last_seen_draw:
                last_seen_draw[n] = draw_idx
                last_seen_date[n] = row.get("draw_date")

    profiles = {}
    for number in universe:
        count = freq.get(number, 0)
        draws_with = sum(1 for d in recent_draws if number in d)
        percentage = round((draws_with / window) * 100, 1)
        draws_since = last_seen_draw.get(number, window)
        days_since = _days_between(last_seen_date.get(number), reference_date)
        trend_key, trend_icon, trend_label = _detect_trend(number, recent_draws)

        profiles[number] = {
            "number": number,
            "count": count,
            "draws_with": draws_with,
            "percentage": percentage,
            "frequency": count,
            "window": window,
            "draws_since": draws_since,
            "days_since": days_since,
            "last_seen_date": last_seen_date.get(number),
            "trend": trend_key,
            "trend_icon": trend_icon,
            "trend_label": trend_label,
        }

    return profiles, window


def _profile_to_hot_detail(profile):
    p = dict(profile)
    p["summary"] = (
        f"Salió {p['count']} veces en últimos {p['window']} sorteos "
        f"({p['percentage']}% de aparición)."
    )
    if p.get("days_since") is not None:
        p["last_seen_text"] = f"Última vez hace {p['days_since']} día(s)."
    return p


def _profile_to_cold_detail(profile):
    p = dict(profile)
    if p["count"] == 0:
        p["summary"] = f"No salió en últimos {p['window']} sorteos."
    elif p["count"] == 1:
        p["summary"] = f"Solo salió 1 vez en últimos {p['window']} sorteos."
    else:
        p["summary"] = (
            f"Solo salió {p['count']} veces en últimos {p['window']} sorteos "
            f"({p['percentage']}% de aparición)."
        )
    return p


def _profile_to_overdue_detail(profile):
    p = dict(profile)
    if p["draws_since"] == 0:
        p["summary"] = f"Salió en el sorteo más reciente ({p['percentage']}% en ventana)."
    else:
        p["summary"] = f"No sale desde hace {p['draws_since']} sorteos."
    if p.get("days_since") is not None and p["draws_since"] > 0:
        p["last_seen_text"] = f"Última vez visto hace {p['days_since']} día(s)."
    return p


def _classify_number_stats(profiles, top_n=TOP_STAT_COUNT):
    if not profiles:
        return [], [], []

    items = list(profiles.values())
    appeared = [p for p in items if p["count"] > 0]

    hot_sorted = sorted(
        appeared,
        key=lambda p: (p["count"], p["percentage"], -p["draws_since"]),
        reverse=True,
    )
    hot = hot_sorted[:top_n]

    cold_pool = sorted(items, key=lambda p: (p["count"], p["percentage"], p["draws_since"]))
    cold = cold_pool[:top_n]

    overdue = sorted(
        items,
        key=lambda p: (p["draws_since"], -p["count"]),
        reverse=True,
    )[:top_n]

    return (
        [_profile_to_hot_detail(p) for p in hot],
        [_profile_to_cold_detail(p) for p in cold],
        [_profile_to_overdue_detail(p) for p in overdue],
    )


def _hot_numbers(freq, top_n=5):
    return [n for n, _ in freq.most_common(top_n)]


def _cold_numbers(freq, universe, top_n=5):
    cold = sorted(universe, key=lambda n: freq.get(n, 0))
    return cold[:top_n]


def _overdue_numbers(results, per_draw, universe):
    last_seen = {}
    for idx, nums in enumerate(per_draw):
        for n in nums:
            if n not in last_seen:
                last_seen[n] = idx
    overdue = sorted(universe, key=lambda n: last_seen.get(n, len(per_draw)), reverse=True)
    return overdue[:top_n]


def _pair_frequency(per_draw):
    pairs = Counter()
    for nums in per_draw:
        unique = list(dict.fromkeys(nums))
        for pair in combinations(sorted(unique), 2):
            pairs[pair] += 1
    return pairs


def _triple_frequency(per_draw):
    triples = Counter()
    for nums in per_draw:
        unique = list(dict.fromkeys(nums))
        if len(unique) >= 3:
            for triple in combinations(sorted(unique), 3):
                triples[triple] += 1
    return triples


def _repeated_combinations(per_draw):
    combo_counter = Counter()
    for nums in per_draw:
        key = tuple(sorted(nums))
        combo_counter[key] += 1
    return {k: v for k, v in combo_counter.items() if v > 1}


def _position_frequency(per_draw):
    pos_freq = defaultdict(Counter)
    for nums in per_draw:
        for i, n in enumerate(nums):
            pos_freq[i][n] += 1
    return {k: dict(v) for k, v in pos_freq.items()}


def _recent_trend(per_draw, window=10):
    recent = per_draw[:window]
    recent_flat = [n for d in recent for n in d]
    return dict(_frequency_counter(recent_flat).most_common(10))


def _numbers_together(per_draw, top_n=5):
    together = Counter()
    for nums in per_draw:
        unique = list(dict.fromkeys(nums))
        for pair in combinations(sorted(unique), 2):
            together[pair] += 1
    return together.most_common(top_n)


def _resolve_analysis_config(lottery: dict) -> dict:
    """Config de rango/cantidad: LEIDSA primero, luego LOTTERY_CONFIG."""
    from services.leidsa_config import resolve_leidsa_recommendation_config

    leidsa_cfg = resolve_leidsa_recommendation_config(
        lottery.get("name", ""),
        lottery.get("type", ""),
    )
    if leidsa_cfg:
        return leidsa_cfg
    return get_lottery_config(lottery["type"])


def _find_duplicate_numbers(numbers: list) -> list:
    seen: set[str] = set()
    dups: list[str] = []
    for n in numbers:
        if n in seen:
            dups.append(n)
        else:
            seen.add(n)
    return dups


def _fallback_unique_numbers(
    universe: list[str],
    already: list[str],
    need: int,
    pad: int = 2,
) -> list[str]:
    """Completa con números únicos del universo sin inventar duplicados."""
    out = list(already)
    used = set(out)
    for n in universe:
        if n not in used:
            out.append(n)
            used.add(n)
        if len(out) >= need:
            break
    i = 0
    while len(out) < need and universe:
        candidate = universe[i % len(universe)]
        if candidate not in used:
            out.append(candidate)
            used.add(candidate)
        i += 1
    return out[:need]


def analizar_loteria_por_tanda(lottery_id, draw_name):
    lottery = get_lottery(lottery_id)
    if not lottery:
        return None

    results = get_results_for_analysis(lottery_id, draw_name)
    config = _resolve_analysis_config(lottery)

    if len(results) < MIN_RESULTS_FOR_ANALYSIS:
        return {
            "ok": False,
            "message": "Necesitamos más historial para analizar.",
            "total_results": len(results),
        }

    all_nums, per_draw = _extract_all_numbers(results)
    freq = _frequency_counter(all_nums)

    universe = [
        _normalize_number(i, config.get("pad", 2))
        for i in range(config["min"], config["max"] + 1)
    ]

    last_30 = results[:30]
    last_60 = results[:60]
    last_90 = results[:90]

    _, per_30 = _extract_all_numbers(last_30)
    _, per_60 = _extract_all_numbers(last_60)

    analysis_window = min(RECENT_WINDOW_DEFAULT, len(per_draw))
    number_profiles, analysis_window = _build_number_profiles(
        results, per_draw, config, window=RECENT_WINDOW_DEFAULT
    )
    hot_detail, cold_detail, overdue_detail = _classify_number_stats(number_profiles)

    hot = [p["number"] for p in hot_detail]
    cold = [p["number"] for p in cold_detail]
    overdue = [p["number"] for p in overdue_detail]

    pairs = _pair_frequency(per_draw)
    triples = _triple_frequency(per_draw)
    repeated = _repeated_combinations(per_draw)
    position_freq = _position_frequency(per_draw)
    trend = _recent_trend(per_draw)
    together = _numbers_together(per_draw)

    return {
        "ok": True,
        "lottery_id": lottery_id,
        "lottery_name": lottery["name"],
        "draw_name": draw_name,
        "total_results": len(results),
        "last_30_count": len(last_30),
        "last_60_count": len(last_60),
        "last_90_count": len(last_90),
        "hot_numbers": hot,
        "cold_numbers": cold,
        "overdue_numbers": overdue,
        "hot_numbers_detail": hot_detail,
        "cold_numbers_detail": cold_detail,
        "overdue_numbers_detail": overdue_detail,
        "number_profiles": number_profiles,
        "analysis_window": analysis_window,
        "top_pairs": [{"pair": list(p), "count": c} for p, c in pairs.most_common(5)],
        "top_triples": [{"triple": list(t), "count": c} for t, c in triples.most_common(5)],
        "repeated_combinations": [
            {"numbers": list(k), "count": v} for k, v in list(repeated.items())[:5]
        ],
        "position_frequency": position_freq,
        "recent_trend": trend,
        "numbers_together": [{"pair": list(p), "count": c} for p, c in together],
        "frequency_30": dict(_frequency_counter([n for d in per_30 for n in d]).most_common(10)),
        "frequency_60": dict(_frequency_counter([n for d in per_60 for n in d]).most_common(10)),
        "_all_nums": all_nums,
        "_freq": freq,
        "_config": config,
    }


def _score_number(n, stats, position=None):
    score = 0.0
    profiles = stats.get("number_profiles", {})
    profile = profiles.get(n, {})
    freq = stats.get("_freq", Counter())
    total = max(len(stats.get("_all_nums", [])), 1)

    count = profile.get("count", 0)
    pct = profile.get("percentage", 0)
    draws_since = profile.get("draws_since", 0)
    trend = profile.get("trend")

    score += count * 5
    score += pct * 0.45

    if n in stats.get("hot_numbers", []):
        score += 18
    if n in stats.get("overdue_numbers", []):
        score += min(draws_since * 2.2, 22)
    if n in stats.get("cold_numbers", []):
        score += 6

    if trend == "rising":
        score += 14
    elif trend == "falling":
        score -= 6
    elif trend == "overheated":
        score -= 4

    freq_ratio = freq.get(n, 0) / total
    score += freq_ratio * 40

    recent_trend = stats.get("recent_trend", {})
    if n in recent_trend:
        score += recent_trend[n] * 2.5

    if position is not None:
        pos_freq = stats.get("position_frequency", {}).get(position, {})
        if n in pos_freq:
            score += pos_freq[n] * 2

    for pair_info in stats.get("numbers_together", []):
        pair = pair_info["pair"]
        if n in pair:
            score += pair_info["count"] * 1.8

    repeated = stats.get("repeated_combinations", [])
    for combo in repeated:
        nums = combo.get("numbers", [])
        if n in nums:
            score += combo.get("count", 0) * 1.2

    return max(score, 0)


def _pick_numbers(stats, config):
    """Elige números por mejor puntuación; sin duplicados salvo allow_repeat."""
    count = int(config["count"])
    allow_repeat = bool(config.get("allow_repeat", False))
    pad = config.get("pad", 2)

    universe = [_normalize_number(i, pad) for i in range(config["min"], config["max"] + 1)]

    scored: list[tuple[float, str]] = []
    for n in universe:
        score = _score_number(n, stats)
        score += random.uniform(0, 4)
        scored.append((score, n))
    scored.sort(key=lambda x: (-x[0], x[1]))

    if allow_repeat:
        selected = [scored[i % len(scored)][1] for i in range(count)] if scored else []
        return selected

    selected: list[str] = []
    used: set[str] = set()
    for _, n in scored:
        if n in used:
            continue
        selected.append(n)
        used.add(n)
        if len(selected) >= count:
            break

    if len(selected) < count:
        selected = _fallback_unique_numbers(universe, selected, count, pad)

    return selected[:count]


def _build_explanation(numbers, stats):
    parts = []
    profiles = stats.get("number_profiles", {})
    together = stats.get("numbers_together", [])
    window = stats.get("analysis_window", RECENT_WINDOW_DEFAULT)

    for n in numbers:
        p = profiles.get(n, {})
        reasons = []
        if p.get("trend") == "rising":
            reasons.append(f"{n} muestra tendencia al alza 📈")
        elif p.get("trend") == "falling":
            reasons.append(f"{n} muestra caída reciente 📉")
        elif p.get("trend") == "overheated":
            reasons.append(f"{n} está sobrecalentado ⚠️ (muchas apariciones seguidas)")
        if p.get("count", 0) >= 3:
            reasons.append(
                f"salió {p['count']} veces en últimos {window} sorteos ({p.get('percentage', 0)}%)"
            )
        if p.get("draws_since", 0) >= 8:
            reasons.append(f"atrasado: no sale desde hace {p['draws_since']} sorteos")
        if not reasons:
            freq = stats.get("_freq", Counter())
            if freq.get(n, 0) > 0:
                reasons.append(f"{n} tiene frecuencia moderada en el histórico")
            else:
                reasons.append(f"{n} sugerido por balance de combinaciones y repeticiones")

        parts.append(f"{n}: {reasons[0]}")

    pair_notes = []
    for pair_info in together[:3]:
        pair = pair_info["pair"]
        if all(p in numbers for p in pair):
            pair_notes.append(
                f"{' y '.join(pair)} aparecen frecuentemente juntos en el histórico"
            )

    explanation = ". ".join(parts[:3])
    if pair_notes:
        explanation += ". " + pair_notes[0]
    explanation += "."
    return explanation


def _calculate_confidence(score, total_results, numbers, stats):
    profiles = stats.get("number_profiles", {})
    trend_hits = sum(
        1 for n in numbers if profiles.get(n, {}).get("trend") in ("rising", "overheated")
    )
    freq_hits = sum(1 for n in numbers if profiles.get(n, {}).get("count", 0) >= 2)
    overdue_hits = sum(1 for n in numbers if profiles.get(n, {}).get("draws_since", 0) >= 6)

    quality = trend_hits * 4 + freq_hits * 3 + overdue_hits * 2
    adjusted = score + quality

    if total_results >= 60 and adjusted >= 78:
        return "alto"
    if total_results >= 25 and adjusted >= 58:
        return "medio"
    if total_results >= MIN_RESULTS_FOR_ANALYSIS and adjusted >= 45:
        return "medio"
    return "bajo"


def _calculate_overall_score(numbers, stats):
    total = 0
    for i, n in enumerate(numbers):
        total += _score_number(n, stats, position=i)

    avg = total / max(len(numbers), 1)
    profiles = stats.get("number_profiles", {})
    combo_bonus = 0
    for pair_info in stats.get("numbers_together", [])[:5]:
        pair = pair_info["pair"]
        if all(p in numbers for p in pair):
            combo_bonus += pair_info["count"] * 2

    repeat_bonus = 0
    for combo in stats.get("repeated_combinations", [])[:3]:
        nums = combo.get("numbers", [])
        overlap = len(set(nums) & set(numbers))
        if overlap >= 2:
            repeat_bonus += combo.get("count", 3)

    trend_bonus = sum(
        4 for n in numbers if profiles.get(n, {}).get("trend") == "rising"
    )
    data_bonus = min(stats.get("total_results", 0) / 2.5, 20)
    raw = avg + combo_bonus + repeat_bonus + trend_bonus + data_bonus
    return min(max(round(raw), 1), 99)


def _pick_bonus_number(stats, config):
    bonus_min = config.get("bonus_min")
    bonus_max = config.get("bonus_max")
    if bonus_min is None or bonus_max is None:
        return None
    pad = 1 if config.get("max", 99) <= 9 else config.get("pad", 2)
    universe = [_normalize_number(i, pad) for i in range(bonus_min, bonus_max + 1)]
    if not universe:
        return None
    freq = stats.get("_freq", Counter())
    scored = []
    for n in universe:
        s = freq.get(n, 0) + random.uniform(0, 5)
        scored.append((s, n))
    scored.sort(reverse=True)
    top = scored[: min(5, len(scored))]
    weights = [t[0] + 0.1 for t in top]
    return random.choices([t[1] for t in top], weights=weights, k=1)[0]


def _bonus_label_for_type(lottery_type):
    return {
        "powerball": "Powerball",
        "mega_millions": "Mega Ball",
        "lotto": "Extra Shot",
        "pick3": "Fireball",
        "pick4": "Fireball",
    }.get(lottery_type)


def generar_jugada_inteligente(lottery_id, draw_name):
    lottery = get_lottery(lottery_id)
    if not lottery:
        return {"ok": False, "message": "Lotería no encontrada."}

    stats = analizar_loteria_por_tanda(lottery_id, draw_name)
    history_count = (stats or {}).get("total_results", 0)
    if not stats or not stats.get("ok"):
        return {
            "ok": False,
            "message": "Necesitamos más historial para analizar.",
            "history_count": history_count,
        }

    config = _resolve_analysis_config(lottery)
    recommend_count = config["count"]
    generated = _pick_numbers(stats, config)
    duplicates = _find_duplicate_numbers(generated)
    warning = None

    if duplicates and not config.get("allow_repeat"):
        seen: set[str] = set()
        fixed: list[str] = []
        pad = config.get("pad", 2)
        universe = [
            _normalize_number(i, pad)
            for i in range(config["min"], config["max"] + 1)
        ]
        for n in generated:
            if n not in seen:
                fixed.append(n)
                seen.add(n)
        generated = _fallback_unique_numbers(universe, fixed, recommend_count, pad)
        duplicates = _find_duplicate_numbers(generated)
        warning = "Se eliminaron duplicados en la recomendación."

    if history_count < MIN_RESULTS_FOR_ANALYSIS:
        warning = (warning or "") + " Historial limitado; números únicos por balance."

    generated_bonus = _pick_bonus_number(stats, config)
    bonus_label = _bonus_label_for_type(lottery["type"])

    analysis_text = _build_explanation(generated, stats)
    if generated_bonus and bonus_label:
        analysis_text += f" {bonus_label} sugerido: {generated_bonus}."
    score = _calculate_overall_score(generated, stats)
    confidence = _calculate_confidence(
        score, stats["total_results"], generated, stats
    )

    create_prediction(
        lottery_id,
        draw_name,
        generated,
        analysis_text,
        confidence,
        score,
    )

    state_label = lottery.get("state") or (
        "Dominican Republic" if lottery["country"] == "RD" else lottery["country"]
    )

    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "ok": True,
        "country": lottery["country"],
        "state": state_label,
        "lottery": lottery["name"],
        "draw_name": draw_name,
        "recommend_count": recommend_count,
        "generated_numbers": generated,
        "numbers": generated,
        "generated_bonus": generated_bonus,
        "bonus_numbers": [generated_bonus] if generated_bonus else [],
        "bonus_label": bonus_label,
        "confidence_level": confidence,
        "score": score,
        "analysis_text": analysis_text,
        "hot_numbers_detail": stats.get("hot_numbers_detail", []),
        "cold_numbers_detail": stats.get("cold_numbers_detail", []),
        "overdue_numbers_detail": stats.get("overdue_numbers_detail", []),
        "analysis_window": stats.get("analysis_window", RECENT_WINDOW_DEFAULT),
        "total_results": stats.get("total_results", 0),
        "history_count": stats.get("total_results", 0),
        "duplicates_found": duplicates,
        "warning": warning.strip() if warning else None,
        "disclaimer": DISCLAIMER,
        "created_at": now,
    }


def _resolve_draw_name_for_lottery(lottery: dict, draw_label: str) -> str:
    """Convierte '8:00 PM' o label UI → draw_name interno (noche, tarde, …)."""
    from models import get_draw_times
    from services.leidsa_config import get_game_schedule_for_ui

    label = (draw_label or "noche").strip()
    if label.lower() in ("tarde", "noche", "mañana", "tardía", "sorteo"):
        return label.lower().replace("tardía", "tardia") if label == "tardía" else label.lower()

    for d in get_draw_times(lottery["id"], active_only=True):
        if d.get("draw_name") == label:
            return d["draw_name"]
        if d.get("draw_time") == label:
            return d["draw_name"]

    for slot in get_game_schedule_for_ui(lottery.get("name", "")) or []:
        if slot.get("time") == label or slot.get("label") == label:
            return slot.get("draw_name", label)

    try:
        from lottery_schedules import get_schedule_slot
        slot = get_schedule_slot(lottery.get("name", ""), label)
        if slot and slot.get("draw_name"):
            return slot["draw_name"]
    except Exception:
        pass
    return label


def debug_leidsa_recommendation(lottery_name: str, draw_name: str) -> dict:
    """Debug recomendación LEIDSA por nombre de lotería y tanda."""
    from services.leidsa_config import (
        LEIDSA_RECOMMENDATION_CONFIG,
        resolve_leidsa_recommendation_config,
    )

    draw_label = (draw_name or "noche").strip()
    name_q = (lottery_name or "").strip()
    lot = None
    for row in get_all_lotteries(active_only=True):
        if row.get("country") != "RD":
            continue
        if row["name"] == name_q or row["name"].lower() == name_q.lower():
            lot = row
            break
        if name_q.lower() in row["name"].lower():
            lot = row
            break

    if not lot:
        return {
            "ok": False,
            "message": f"Lotería no encontrada: {lottery_name}",
            "lottery": lottery_name,
            "draw": draw_label,
        }

    draw_resolved = _resolve_draw_name_for_lottery(lot, draw_label)
    cfg = resolve_leidsa_recommendation_config(lot["name"], lot.get("type", ""))
    raw_cfg = LEIDSA_RECOMMENDATION_CONFIG.get(lot["name"])

    result = generar_jugada_inteligente(lot["id"], draw_resolved)
    nums = result.get("generated_numbers") or result.get("numbers") or []

    return {
        "ok": result.get("ok", False),
        "lottery": lot["name"],
        "draw": draw_resolved,
        "draw_label": draw_label,
        "recommend_count": (cfg or {}).get("count") or (raw_cfg or {}).get("recommend_count"),
        "numbers": nums,
        "duplicates_found": _find_duplicate_numbers(nums),
        "history_count": result.get("history_count", result.get("total_results", 0)),
        "allow_duplicates": (raw_cfg or {}).get("allow_duplicates", False),
        "config": raw_cfg,
        "warning": result.get("warning"),
        "message": result.get("message"),
        "score": result.get("score"),
    }
