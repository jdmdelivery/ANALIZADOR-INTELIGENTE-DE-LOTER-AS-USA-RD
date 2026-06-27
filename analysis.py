import random
import os
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
RECENT_EXCLUSION_DRAWS = 5
MIN_DRAWS_SINCE_FOR_OVERDUE = 2
MIN_DRAWS_SINCE_FOR_HOT_DISPLAY = 1
LAST_DRAW_SCORE_CAP = 0.0
RECENT_APPEARANCE_PENALTY = 55.0
ANALYSIS_BASIS_TEXT = "Basado en análisis histórico y tendencias recientes"
USA_ANALYSIS_MAX_RESULTS = 100
USA_ANALYSIS_LOG_PREFIX = "[USA ANALISIS]"
ANALYSIS_BUILD = f"{os.path.getmtime(__file__):.0f}"


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


def _collect_recent_drawn_numbers(per_draw, num_draws=RECENT_EXCLUSION_DRAWS):
    """Números que salieron en los últimos N sorteos (para excluir de recomendación)."""
    excluded: set[str] = set()
    for draw in per_draw[:num_draws]:
        excluded.update(draw)
    return excluded


def _collect_last_draw_numbers(per_draw):
    if not per_draw:
        return set()
    return set(per_draw[0])


def _recency_penalty(number, stats):
    """Penalización fuerte si salió en el último sorteo o en ventana reciente."""
    last_draw = stats.get("last_draw_numbers") or set()
    excluded = stats.get("excluded_recent_numbers") or set()
    profiles = stats.get("number_profiles", {})
    draws_since = profiles.get(number, {}).get("draws_since", 999)

    if number in last_draw or draws_since == 0:
        return RECENT_APPEARANCE_PENALTY * 4
    if number in excluded:
        return RECENT_APPEARANCE_PENALTY * 2
    if draws_since == 1:
        return RECENT_APPEARANCE_PENALTY
    return 0.0


def _classify_number_stats(
    profiles,
    top_n=TOP_STAT_COUNT,
    last_draw_numbers=None,
    min_overdue_draws=MIN_DRAWS_SINCE_FOR_OVERDUE,
):
    if not profiles:
        return [], [], []

    last_draw = last_draw_numbers or set()
    items = list(profiles.values())

    hot_pool = [
        p for p in items
        if p["count"] > 0 and p["number"] not in last_draw and p["draws_since"] >= MIN_DRAWS_SINCE_FOR_HOT_DISPLAY
    ]
    if len(hot_pool) < top_n:
        hot_pool = [p for p in items if p["count"] > 0 and p["number"] not in last_draw]
    hot_sorted = sorted(
        hot_pool,
        key=lambda p: (p["count"], p["percentage"], p["draws_since"]),
        reverse=True,
    )
    hot = hot_sorted[:top_n]

    cold_pool = sorted(
        [p for p in items if p["number"] not in last_draw],
        key=lambda p: (p["count"], p["percentage"], p["draws_since"]),
    )
    cold = cold_pool[:top_n]

    overdue_pool = [
        p for p in items
        if p["draws_since"] >= min_overdue_draws and p["number"] not in last_draw
    ]
    overdue = sorted(
        overdue_pool,
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


def _overdue_numbers(per_draw, universe, top_n=TOP_STAT_COUNT, min_draws_since=MIN_DRAWS_SINCE_FOR_OVERDUE):
    last_seen = {}
    for idx, nums in enumerate(per_draw):
        for n in nums:
            if n not in last_seen:
                last_seen[n] = idx
    last_draw = _collect_last_draw_numbers(per_draw)
    overdue = sorted(
        [n for n in universe if n not in last_draw and last_seen.get(n, len(per_draw)) >= min_draws_since],
        key=lambda n: last_seen.get(n, len(per_draw)),
        reverse=True,
    )
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


def _is_illinois_lotto(lottery: dict | None) -> bool:
    if not lottery:
        return False
    if lottery.get("country") != "USA":
        return False
    return (lottery.get("name") or "").strip().lower() == "illinois lotto"


def es_combinacion_valida_illinois_lotto(nums: list) -> bool:
    """Illinois Lotto: 6 números únicos entre 1 y 50."""
    if len(nums) != 6:
        return False
    seen: set[int] = set()
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            return False
        if v < 1 or v > 50:
            return False
        if v in seen:
            return False
        seen.add(v)
    return True


def _filter_draw_numbers_for_config(nums: list, config: dict) -> list:
    lo, hi = int(config["min"]), int(config["max"])
    pad = config.get("pad", 2)
    out: list[str] = []
    for raw in nums:
        try:
            v = int(str(raw).lstrip("0") or "0")
        except (TypeError, ValueError):
            continue
        if lo <= v <= hi:
            out.append(_normalize_number(v, pad))
    return out


def _resolve_analysis_config(lottery: dict) -> dict:
    """Config de rango/cantidad: LEIDSA primero, luego LOTTERY_CONFIG."""
    from services.leidsa_config import resolve_leidsa_recommendation_config

    leidsa_cfg = resolve_leidsa_recommendation_config(
        lottery.get("name", ""),
        lottery.get("type", ""),
    )
    if leidsa_cfg:
        return leidsa_cfg
    cfg = dict(get_lottery_config(lottery["type"]))
    if _is_illinois_lotto(lottery):
        cfg.update({"count": 6, "min": 1, "max": 50, "allow_repeat": False, "pad": 2})
    return cfg


def _find_duplicate_numbers(numbers: list) -> list:
    seen: set[str] = set()
    dups: list[str] = []
    for n in numbers:
        if n in seen:
            dups.append(n)
        else:
            seen.add(n)
    return dups


def _is_pick4_strict(config: dict) -> bool:
    """Illinois Pick 4 — reglas estrictas de variedad (no aplica RD)."""
    return bool(config.get("pick4_strict")) and int(config.get("count", 0)) == 4


def es_combinacion_valida_pick4(nums: list) -> bool:
    if len(nums) != 4:
        return False
    conteo = Counter(nums)
    if max(conteo.values()) > 2:
        return False
    if len(set(nums)) < 3:
        return False
    return True


def _pick4_tier_pools(stats: dict, config: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    """Caliente, frío, atrasado, neutral para Pick 4."""
    pickable = _pickable_digits(stats, config, strict=False)
    hot = [n for n in (stats.get("hot_numbers") or []) if n in pickable]
    cold = [n for n in (stats.get("cold_numbers") or []) if n in pickable]
    overdue = [n for n in (stats.get("overdue_numbers") or []) if n in pickable]
    tier_used = set(hot + cold + overdue)
    scored, _ = _scored_pickable_pool(stats, config, strict=False)
    neutral = [n for n in [x for _, x in scored] if n in pickable and n not in tier_used]
    if not neutral:
        neutral = [n for n in pickable if n not in tier_used] or list(pickable)
    if not hot:
        hot = list(pickable)
    if not cold:
        cold = [n for n in pickable if n not in hot] or list(pickable)
    if not overdue:
        overdue = [n for n in pickable if n not in hot and n not in cold] or list(pickable)
    return hot, cold, overdue, neutral


def _pick4_dominant(nums: list) -> str | None:
    if not nums:
        return None
    return Counter(nums).most_common(1)[0][0]


def _generar_pick4(stats: dict, config: dict) -> list[str]:
    """Un intento de 4 dígitos con mezcla caliente/frío/atrasado/neutral."""
    count = 4
    max_r = 2
    hot, cold, overdue, neutral = _pick4_tier_pools(stats, config)
    tier_lists = [hot, cold, overdue, neutral]
    pickable = _pickable_digits(stats, config, strict=False)
    last_draw = set(stats.get("last_draw_numbers") or [])

    result: list[str] = []
    counts: Counter = Counter()

    for i in range(count):
        preferred = tier_lists[i % len(tier_lists)]
        search = [preferred] + [t for j, t in enumerate(tier_lists) if j != i % len(tier_lists)] + [pickable]
        placed = None
        for tier in search:
            random.shuffle(tier)
            for n in tier:
                if counts[n] >= max_r:
                    continue
                if n in last_draw and len(pickable) > len(last_draw):
                    continue
                trial = result + [n]
                if len(trial) == count and len(set(trial)) < 3:
                    continue
                placed = n
                break
            if placed:
                break
        if not placed:
            opts = [n for n in pickable if counts[n] < max_r]
            if opts:
                placed = random.choice(opts)
            else:
                placed = random.choice(pickable)
        result.append(placed)
        counts[placed] += 1

    return result[:count]


def _pick4_safe_mix(stats: dict, config: dict) -> list[str]:
    """Fallback: 4 dígitos distintos — 1 caliente, 1 frío, 1 atrasado, 1 neutral."""
    hot, cold, overdue, neutral = _pick4_tier_pools(stats, config)
    picks: list[str] = []
    seen: set[str] = set()
    for tier in (hot, cold, overdue, neutral):
        for n in tier:
            if n in seen:
                continue
            picks.append(n)
            seen.add(n)
            break
        if len(picks) >= 4:
            break
    if len(picks) < 4:
        for n in _pickable_digits(stats, config, strict=False):
            if n not in seen:
                picks.append(n)
                seen.add(n)
            if len(picks) >= 4:
                break
    pad = config.get("pad", 1)
    if len(picks) < 4:
        for i in range(config["min"], config["max"] + 1):
            n = _normalize_number(i, pad)
            if n not in seen:
                picks.append(n)
                seen.add(n)
            if len(picks) >= 4:
                break
    return picks[:4]


def _generate_pick4_recommendation(stats: dict, config: dict) -> tuple[list[str], bool]:
    """Pick 4 Illinois: hasta 50 intentos + mezcla segura."""
    regenerated = False
    nums: list[str] = []
    for _ in range(50):
        nums = _generar_pick4(stats, config)
        if es_combinacion_valida_pick4(nums):
            return nums, regenerated
        regenerated = True
    nums = _pick4_safe_mix(stats, config)
    if not es_combinacion_valida_pick4(nums):
        pad = config.get("pad", 1)
        nums = [_normalize_number(i, pad) for i in range(4)]
    return nums, True


def _digit_game_variety(config: dict) -> bool:
    """Solo Pick 3/4 USA usan tope de repetición y variedad mínima."""
    return "max_repeat_per_number" in config and "min_unique" in config


def _pickable_digits(stats: dict, config: dict, strict: bool = True) -> list[str]:
    pad = config.get("pad", 2)
    universe = [
        _normalize_number(i, pad)
        for i in range(config["min"], config["max"] + 1)
    ]
    if strict:
        pool = [n for n in universe if _is_pickable_number(n, stats)]
        if pool:
            return pool
    last = set(stats.get("last_draw_numbers") or [])
    pool = [n for n in universe if n not in last]
    return pool or universe


def _max_repeat_for_config(config: dict) -> int:
    if not config.get("allow_repeat"):
        return 1
    return int(config.get("max_repeat_per_number", 2))


def _min_unique_for_config(config: dict) -> int:
    if "min_unique" in config:
        return int(config["min_unique"])
    count = int(config["count"])
    if config.get("allow_repeat"):
        return min(count, max(2, (count + 1) // 2))
    return count


def _reportable_duplicates(numbers: list, config: dict) -> list:
    """Duplicados fuera del límite permitido por lotería."""
    if not config.get("allow_repeat"):
        return _find_duplicate_numbers(numbers)
    max_r = _max_repeat_for_config(config)
    counts = Counter(numbers)
    dups: list[str] = []
    for n, c in counts.items():
        if c > max_r:
            dups.extend([n] * (c - max_r))
    return dups


def _is_recommendation_acceptable(numbers: list, config: dict, stats: dict) -> bool:
    count = int(config["count"])
    if len(numbers) != count:
        return False
    if _is_pick4_strict(config):
        if not es_combinacion_valida_pick4(numbers):
            return False
        per_draw = stats.get("_per_draw") or []
        if per_draw and numbers == per_draw[0][:4]:
            return False
        return True
    if stats.get("_illinois_lotto"):
        if not es_combinacion_valida_illinois_lotto(numbers):
            return False
    if not _digit_game_variety(config):
        return all(_is_pickable_number(n, stats) for n in numbers)
    pickable = _pickable_digits(stats, config, strict=False)
    min_u = min(_min_unique_for_config(config), len(pickable))
    if len(set(numbers)) <= 1 and len(pickable) > 1:
        return False
    if len(set(numbers)) < min_u:
        return False
    if any(c > _max_repeat_for_config(config) for c in Counter(numbers).values()):
        return False
    per_draw = stats.get("_per_draw") or []
    if per_draw and len(per_draw[0]) >= count and numbers == per_draw[0][:count]:
        return False
    last = set(stats.get("last_draw_numbers") or [])
    if any(n in last for n in numbers) and len(pickable) > len(last):
        return False
    return True


def _scored_pickable_pool(stats: dict, config: dict, strict: bool = True) -> tuple[list[tuple[float, str]], list[str]]:
    pad = config.get("pad", 2)
    pickable = _pickable_digits(stats, config, strict=strict)
    scored: list[tuple[float, str]] = []
    for n in pickable:
        scored.append((_score_number(n, stats) + random.uniform(0, 4.0), n))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored, pickable


def _ordered_tier_candidates(stats: dict, config: dict) -> list[str]:
    """Pool ordenado: caliente → atrasado → frío → puntuación."""
    scored, pickable = _scored_pickable_pool(stats, config)
    ranked = [n for _, n in scored]
    tiers = [
        [n for n in (stats.get("hot_numbers") or []) if _is_pickable_number(n, stats)],
        [n for n in (stats.get("overdue_numbers") or []) if _is_pickable_number(n, stats)],
        [n for n in (stats.get("cold_numbers") or []) if _is_pickable_number(n, stats)],
        ranked,
        pickable,
    ]
    out: list[str] = []
    seen: set[str] = set()
    for tier in tiers:
        for n in tier:
            if n not in seen:
                out.append(n)
                seen.add(n)
    return out or pickable


def _pick_varied_recommendation(stats: dict, config: dict) -> list[str]:
    """Pick 3/4: mezcla natural caliente/frío/atrasado/tendencia con repetición limitada."""
    count = int(config["count"])
    max_r = _max_repeat_for_config(config)
    candidates = _ordered_tier_candidates(stats, config)
    scored, pickable = _scored_pickable_pool(stats, config, strict=True)
    if len(pickable) < _min_unique_for_config(config):
        scored, pickable = _scored_pickable_pool(stats, config, strict=False)

    result: list[str] = []
    counts: Counter = Counter()
    hot = [n for n in (stats.get("hot_numbers") or []) if n in pickable]
    overdue = [n for n in (stats.get("overdue_numbers") or []) if n in pickable]
    cold = [n for n in (stats.get("cold_numbers") or []) if n in pickable]
    ranked = [n for _, n in scored]
    if len(candidates) < _min_unique_for_config(config):
        for n in pickable:
            if n not in candidates:
                candidates.append(n)
    tier_lists = [hot, overdue, cold, ranked, pickable]

    for i in range(count):
        preferred_tiers = tier_lists[i % len(tier_lists):] + tier_lists[: i % len(tier_lists)]
        placed = None
        for tier in preferred_tiers:
            for n in tier:
                if counts[n] >= max_r:
                    continue
                if n in set(stats.get("last_draw_numbers") or []) and len(pickable) > len(stats.get("last_draw_numbers") or []):
                    continue
                if result and n == result[-1] and len(set(candidates)) > 1:
                    continue
                placed = n
                break
            if placed:
                break
        if not placed:
            for n in candidates:
                if counts[n] < max_r and _is_pickable_number(n, stats):
                    if not (result and n == result[-1] and len(set(candidates)) > 1):
                        placed = n
                        break
        if not placed:
            for n in random.sample(pickable, len(pickable)):
                if counts[n] < max_r:
                    placed = n
                    break
        if not placed:
            placed = random.choice(pickable)
        result.append(placed)
        counts[placed] += 1

    while len(result) < count and pickable:
        n = random.choice(pickable)
        if counts[n] < max_r:
            result.append(n)
            counts[n] += 1
        elif len(set(pickable)) == 1:
            result.append(n)
            counts[n] += 1
        else:
            opts = [x for x in pickable if counts[x] < max_r] or pickable
            result.append(random.choice(opts))
            counts[result[-1]] += 1

    return _enforce_variety(result[:count], stats, config)


def _enforce_variety(numbers: list, stats: dict, config: dict) -> list[str]:
    """Garantiza variedad mínima y tope de repetición por dígito."""
    count = int(config["count"])
    min_u = _min_unique_for_config(config)
    max_r = _max_repeat_for_config(config)
    numbers = list(numbers[:count])
    _, pickable = _scored_pickable_pool(stats, config)

    for _ in range(count * 3):
        counts = Counter(numbers)
        if len(set(numbers)) >= min_u and all(c <= max_r for c in counts.values()):
            break
        changed = False
        for idx, n in enumerate(numbers):
            if counts[n] <= max_r and len(set(numbers)) >= min_u:
                continue
            for alt in pickable:
                trial = list(numbers)
                trial[idx] = alt
                tc = Counter(trial)
                if tc[alt] > max_r:
                    continue
                if len(set(trial)) < min(min_u, len(trial)):
                    continue
                numbers = trial
                changed = True
                break
            if changed:
                break
        if not changed:
            break

    if len(set(numbers)) <= 1 and pickable:
        base = numbers[0] if numbers else pickable[0]
        alts = [n for n in pickable if n != base]
        numbers = [base]
        for n in alts:
            if len(numbers) >= count:
                break
            numbers.append(n)
        while len(numbers) < count and alts:
            numbers.append(random.choice(alts))

    return numbers[:count]


def _generate_recommendation(stats: dict, config: dict, max_attempts: int = 8) -> tuple[list[str], bool]:
    """Genera recomendación válida; regenera si hay demasiados duplicados."""
    if _is_pick4_strict(config):
        return _generate_pick4_recommendation(stats, config)

    regenerated = False
    for _ in range(max_attempts):
        if _digit_game_variety(config):
            nums = _pick_varied_recommendation(stats, config)
        else:
            nums = _pick_numbers(stats, config)
            nums = _sanitize_recommendation(nums, stats, config)
        if _is_recommendation_acceptable(nums, config, stats):
            return nums, regenerated
        regenerated = True
    nums = (
        _pick_varied_recommendation(stats, config)
        if _digit_game_variety(config)
        else _pick_balanced_random(
            [
                _normalize_number(i, config.get("pad", 2))
                for i in range(config["min"], config["max"] + 1)
            ],
            set(stats.get("excluded_recent_numbers") or [])
            | set(stats.get("last_draw_numbers") or []),
            int(config["count"]),
            config.get("pad", 2),
            allow_repeat=False,
        )
    )
    return _enforce_variety(nums, stats, config) if _digit_game_variety(config) else nums, True


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
    if len(out) >= need or not universe:
        return out[:need]
    i = 0
    max_passes = len(universe) * max(need - len(out), 1) + 1
    while len(out) < need and i < max_passes:
        candidate = universe[i % len(universe)]
        if candidate not in used:
            out.append(candidate)
            used.add(candidate)
        i += 1
    return out[:need]


def analizar_loteria_por_tanda(lottery_id, draw_name, max_results=None):
    from services.recommendations.engine import build_analysis_stats

    return build_analysis_stats(lottery_id, draw_name, max_results=max_results)


def _is_pickable_number(n, stats):
    """Nunca elegible si salió en el último sorteo o en la ventana de exclusión reciente."""
    last_draw = set(stats.get("last_draw_numbers") or [])
    excluded = set(stats.get("excluded_recent_numbers") or [])
    profiles = stats.get("number_profiles", {})
    draws_since = profiles.get(n, {}).get("draws_since", 999)

    if n in last_draw or draws_since == 0:
        return False
    if n in excluded:
        return False
    return True


def _score_number(n, stats, position=None):
    if not _is_pickable_number(n, stats):
        return LAST_DRAW_SCORE_CAP

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
        score -= 12

    freq_ratio = freq.get(n, 0) / total
    score += freq_ratio * 40

    recent_trend = stats.get("recent_trend", {})
    if n in recent_trend:
        score += recent_trend[n] * 1.5

    if draws_since >= 8:
        score += min(draws_since * 1.5, 18)

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

    score -= _recency_penalty(n, stats) * 0.15
    return max(score, 0)


def _pick_balanced_random(universe, excluded, count, pad=2, allow_repeat=False, max_repeat=2):
    """Recomendación balanceada cuando hay pocos datos; nunca incluye exclusión reciente."""
    pool = [n for n in universe if n not in excluded]
    if not pool:
        pool = list(universe)
    if allow_repeat and pool:
        result: list[str] = []
        counts: Counter = Counter()
        for _ in range(count):
            opts = [n for n in pool if counts[n] < max_repeat] or pool
            if result and len(set(pool)) > 1:
                opts = [n for n in opts if n != result[-1]] or opts
            n = random.choice(opts)
            result.append(n)
            counts[n] += 1
        return result
    random.shuffle(pool)
    return pool[:count]


def _sanitize_recommendation(numbers, stats, config):
    """Quita duplicados y números del último sorteo / ventana reciente."""
    count = int(config["count"])
    pad = config.get("pad", 2)
    allow_repeat = bool(config.get("allow_repeat", False))
    universe = [_normalize_number(i, pad) for i in range(config["min"], config["max"] + 1)]
    excluded = set(stats.get("excluded_recent_numbers") or [])
    excluded.update(stats.get("last_draw_numbers") or [])

    if allow_repeat and _digit_game_variety(config):
        return _enforce_variety(
            [n for n in numbers if n not in set(stats.get("last_draw_numbers") or [])][:count]
            or [n for n in numbers if _is_pickable_number(n, stats)][:count],
            stats,
            config,
        )

    if allow_repeat:
        cleaned = [n for n in numbers if _is_pickable_number(n, stats)][:count]
        pool = [n for n in universe if _is_pickable_number(n, stats)] or list(universe)
        while len(cleaned) < count and pool:
            cleaned.append(random.choice(pool))
        return cleaned[:count]

    seen: set[str] = set()
    cleaned: list[str] = []
    for n in numbers:
        if n in seen or not _is_pickable_number(n, stats):
            continue
        cleaned.append(n)
        seen.add(n)

    if len(cleaned) < count:
        cleaned = _fallback_unique_numbers(
            [n for n in universe if n not in excluded],
            cleaned,
            count,
            pad,
        )

    if len(cleaned) < count:
        cleaned = _pick_balanced_random(universe, excluded, count, pad, allow_repeat=False)

    return cleaned[:count]


def _pick_numbers(stats, config):
    """Elige números por mejor puntuación; sin duplicados salvo allow_repeat."""
    count = int(config["count"])
    allow_repeat = bool(config.get("allow_repeat", False))
    pad = config.get("pad", 2)

    universe = [_normalize_number(i, pad) for i in range(config["min"], config["max"] + 1)]
    excluded = set(stats.get("excluded_recent_numbers") or [])
    excluded.update(stats.get("last_draw_numbers") or [])

    pickable = [n for n in universe if _is_pickable_number(n, stats)]
    if not pickable:
        return _pick_balanced_random(universe, excluded, count, pad, allow_repeat=allow_repeat)

    scored: list[tuple[float, str]] = []
    for n in pickable:
        score = _score_number(n, stats)
        score += random.uniform(0, 5.5)
        scored.append((score, n))
    scored.sort(key=lambda x: (-x[0], x[1]))

    if allow_repeat and _digit_game_variety(config):
        return _pick_varied_recommendation(stats, config)

    if allow_repeat:
        selected = [scored[i % len(scored)][1] for i in range(count)] if scored else []
        return _sanitize_recommendation(selected, stats, config)

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
        pool = [n for n in universe if n not in excluded and n not in used]
        selected = _fallback_unique_numbers(pool, selected, count, pad)

    return _sanitize_recommendation(selected[:count], stats, config)


def _schedule_emoji(draw_name: str) -> str:
    key = (draw_name or "").lower().replace("tardía", "tardia")
    return {
        "mañana": "🌅",
        "manana": "🌅",
        "tarde": "🌇",
        "tardia": "🎯",
        "noche": "🌙",
    }.get(key, "🎱")


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
    hot = set(stats.get("hot_numbers") or [])
    cold = set(stats.get("cold_numbers") or [])
    overdue = set(stats.get("overdue_numbers") or [])

    trend_hits = sum(
        1 for n in numbers if profiles.get(n, {}).get("trend") in ("rising", "overheated")
    )
    freq_hits = sum(1 for n in numbers if profiles.get(n, {}).get("count", 0) >= 2)
    overdue_hits = sum(1 for n in numbers if profiles.get(n, {}).get("draws_since", 0) >= 6)
    hot_hits = sum(1 for n in numbers if n in hot)
    cold_hits = sum(1 for n in numbers if n in cold)
    mix_bonus = 0
    if hot_hits:
        mix_bonus += 4
    if cold_hits:
        mix_bonus += 3
    if overdue_hits or any(n in overdue for n in numbers):
        mix_bonus += 4

    unique_ratio = len(set(numbers)) / max(len(numbers), 1)
    variety_bonus = 8 if unique_ratio >= 0.75 else (4 if unique_ratio >= 0.5 else 0)
    dup_penalty = 0
    if len(set(numbers)) <= 1:
        dup_penalty = 45
    elif len(_find_duplicate_numbers(numbers)) >= 3:
        dup_penalty = 18

    quality = trend_hits * 4 + freq_hits * 3 + overdue_hits * 2 + mix_bonus + variety_bonus
    adjusted = score + quality - dup_penalty

    if total_results >= 60 and adjusted >= 78 and unique_ratio >= 0.5:
        return "alto"
    if total_results >= 25 and adjusted >= 58 and unique_ratio >= 0.4:
        return "medio"
    if total_results >= MIN_RESULTS_FOR_ANALYSIS and adjusted >= 45:
        return "medio"
    return "bajo"


def _confidence_label(level: str) -> str:
    return {"alto": "Alto", "medio": "Medio", "bajo": "Bajo"}.get(level, "Bajo")


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


def _pick_bonus_number(stats, config, main_numbers=None):
    bonus_min = config.get("bonus_min")
    bonus_max = config.get("bonus_max")
    if bonus_min is None or bonus_max is None:
        return None
    pad = 1 if config.get("max", 99) <= 9 else config.get("pad", 2)
    universe = [_normalize_number(i, pad) for i in range(bonus_min, bonus_max + 1)]
    if not universe:
        return None
    per_draw = stats.get("_per_draw") or []
    last_bonus = set()
    for draw in per_draw[:RECENT_EXCLUSION_DRAWS]:
        for n in draw:
            if bonus_min <= int(n) <= bonus_max:
                last_bonus.add(_normalize_number(int(n), pad))
    pool = [n for n in universe if n not in last_bonus] or universe
    if main_numbers:
        mains = set(main_numbers)
        if _is_pick4_strict(config):
            dominant = _pick4_dominant(main_numbers)
            if dominant:
                alt = [n for n in pool if n != dominant]
                if alt:
                    pool = alt
        else:
            varied = [n for n in pool if n not in mains]
            if varied:
                pool = varied
            elif len(set(main_numbers)) == 1:
                dominant = main_numbers[0]
                alt = [n for n in pool if n != dominant]
                if alt:
                    pool = alt
    freq = stats.get("_freq", Counter())
    scored = []
    for n in pool:
        s = freq.get(n, 0) + random.uniform(0, 5)
        scored.append((s, n))
    scored.sort(reverse=True)
    top = scored[: min(5, len(scored))]
    if not top:
        top = [(0.0, n) for n in pool[:5]]
    weights = [t[0] + 0.1 for t in top]
    bonus = random.choices([t[1] for t in top], weights=weights, k=1)[0]
    if _is_pick4_strict(config) and main_numbers:
        dominant = _pick4_dominant(main_numbers)
        if dominant and bonus == dominant:
            alts = [n for n in universe if n != dominant and n not in last_bonus]
            if not alts:
                alts = [n for n in universe if n != dominant]
            bonus = random.choice(alts) if alts else bonus
    return bonus


def _bonus_label_for_type(lottery_type):
    return {
        "powerball": "Powerball",
        "mega_millions": "Mega Ball",
        "lotto": "Extra Shot",
        "pick3": "Fireball",
        "pick4": "Fireball",
    }.get(lottery_type)


def generar_jugada_inteligente(lottery_id, draw_name, force_refresh=True):
    from services.recommendations.engine import generate_recommendation

    return generate_recommendation(lottery_id, draw_name, force_refresh=force_refresh)


def _resolve_draw_name_for_lottery(lottery: dict, draw_label: str) -> str:
    """Convierte '6:00 PM', 'Tardía' o draw_name interno → tarde / tardía / noche / …"""
    from models import get_draw_times
    from services.leidsa_config import get_game_schedule_for_ui
    from lottery_schedules import get_lottery_schedule, slot_draw_name, time_12h_to_24h

    label = (draw_label or "noche").strip()
    if not label:
        return "noche"

    folded = label.casefold()
    schedule = get_game_schedule_for_ui(lottery.get("name", "")) or get_lottery_schedule(
        lottery.get("name", "")
    )
    if schedule:
        for slot in schedule:
            dn = slot_draw_name(slot)
            if folded == dn.casefold():
                return dn
            if folded == (slot.get("label") or "").casefold():
                return dn
            if label == slot.get("time") or folded == (slot.get("time") or "").casefold():
                return dn
            dt24 = time_12h_to_24h(slot.get("time", ""))
            if dt24 and (label == dt24 or folded == dt24.casefold()):
                return dn

    for d in get_draw_times(lottery["id"], active_only=True):
        if d.get("draw_name") == label or (d.get("draw_name") or "").casefold() == folded:
            return d["draw_name"]
        if d.get("draw_time") == label:
            return d["draw_name"]

    aliases = {
        "manana": "mañana",
        "tardia": "tardía",
        "tarde": "tarde",
        "tardía": "tardía",
        "noche": "noche",
        "sorteo": "sorteo",
    }
    if folded in aliases:
        return aliases[folded]

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
