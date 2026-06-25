"""Pick 2/3/4/5 — Top 5 y Top 10 combinaciones, Fireball separado."""
from __future__ import annotations

import random
from itertools import product

from services.recommendations.adapters.base import BaseAdapter
from services.recommendations.categories import (
    assign_category,
    build_hot_cold_lists,
    category_explanation,
    category_label,
    classify_number,
    position_frequency,
)
from services.recommendations.constants import BONUS_LABELS, MIN_HISTORY, STRONG_RECOMMENDATION_MIN
from services.recommendations.scoring import (
    confidence_from_score,
    format_score_breakdown,
    is_strong_recommendation,
    score_combination,
    score_number,
)


def _normalize(n: str, pad: int = 1) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(pad)


class PickAdapter(BaseAdapter):
    adapter_key = "pick"
    game_type_label = "Pick"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        per_bonus = ctx.get("per_draw_bonus") or []
        if len(per_draw) < MIN_HISTORY:
            return self.insufficient(ctx, len(per_draw))

        pad = int(config.get("pad", 1))
        count = int(config["count"])
        lo, hi = int(config["min"]), int(config["max"])
        universe = [_normalize(i, pad) for i in range(lo, hi + 1)]
        weights = ctx.get("weights")
        pos_freq = position_frequency(per_draw, 100)

        profiles: dict[str, dict] = {}
        categories: dict[str, str] = {}
        for num in universe:
            prof = classify_number(num, per_draw, pad=pad, window=25)
            cat = assign_category(prof)
            categories[num] = cat
            s, sexp = score_number(
                num, per_draw, weights=weights, position_freq=pos_freq
            )
            profiles[num] = {
                **prof,
                "category": cat,
                "category_label": category_label(cat),
                "score": s,
                "reason": category_explanation(cat, prof),
                "score_breakdown": format_score_breakdown(sexp),
            }

        hot, cold = build_hot_cold_lists(profiles, categories)
        overdue = sorted(
            [p for n, p in profiles.items() if p["category"] in ("atrasado", "caliente_atrasado")],
            key=lambda p: -p.get("draws_since", 0),
        )[:10]

        top5 = self._top_combos(per_draw, profiles, count, pad, 5, config)
        top10 = self._top_combos(per_draw, profiles, count, pad, 10, config)
        primary = top5[0]["numbers"] if top5 else self._fallback_combo(universe, count)
        combo_score = top5[0]["score"] if top5 else 0
        conf_key, conf_label = confidence_from_score(combo_score)
        strong = is_strong_recommendation(combo_score)

        lot_type = ctx["lottery"].get("type", "pick3")
        bonus_label = BONUS_LABELS.get(lot_type, "Fireball")
        fireball = self._score_fireball(per_bonus, per_draw, config, primary)
        fireball_alts = self._fireball_alternatives(fireball, config, count=3)

        digit_parts = []
        for i, n in enumerate(primary):
            s, exp = score_number(
                n, per_draw, weights=weights, position=i, position_freq=pos_freq
            )
            digit_parts.append({
                "position": i + 1,
                "number": n,
                "score": s,
                "reason": profiles.get(n, {}).get("reason", ""),
                "score_breakdown": format_score_breakdown(exp),
            })

        analysis = "; ".join(f"Pos{i+1}: {d['number']} ({d['score']})" for i, d in enumerate(digit_parts))
        if fireball.get("number"):
            analysis += f". {bonus_label}: {fireball['number']} (score {fireball.get('score', 0)})."

        meta = self.base_meta(ctx, config, "pick")
        return {
            "ok": True,
            **meta,
            "generated_numbers": primary,
            "numbers": primary,
            "recommended_numbers": primary,
            "recommend_count": count,
            "score": combo_score,
            "confidence_level": conf_key,
            "confidence_label": conf_label,
            "is_strong_recommendation": strong,
            "analysis_text": analysis,
            "digit_scores": digit_parts,
            "top_combinations": {"top_5": top5, "top_10": top10},
            "generated_bonus": fireball.get("number"),
            "bonus_numbers": [fireball["number"]] if fireball.get("number") else [],
            "bonus_label": bonus_label,
            "fireball": fireball,
            "fireball_alternatives": fireball_alts,
            "hot_numbers": [p["number"] for p in hot],
            "cold_numbers": [p["number"] for p in cold],
            "overdue_numbers": [p["number"] for p in overdue],
            "hot_numbers_detail": hot,
            "cold_numbers_detail": cold,
            "overdue_numbers_detail": overdue,
            "position_frequency": {k: dict(v) for k, v in pos_freq.items()},
            "total_results": len(per_draw),
            "analysis_window": 25,
        }

    def _top_combos(
        self,
        per_draw: list,
        profiles: dict,
        count: int,
        pad: int,
        limit: int,
        config: dict,
    ) -> list[dict]:
        ranked_digits = sorted(profiles.values(), key=lambda p: -p["score"])
        top_digits = [p["number"] for p in ranked_digits[: min(8, len(ranked_digits))]]
        if len(top_digits) < count:
            top_digits = list(profiles.keys())[:count]

        allow_repeat = config.get("allow_repeat", True)
        max_repeat = int(config.get("max_repeat_per_number", 2))
        combos: list[dict] = []
        seen: set[tuple] = set()

        def gen_slots():
            if allow_repeat:
                for tpl in product(top_digits, repeat=count):
                    yield list(tpl)
            else:
                from itertools import permutations
                for tpl in permutations(top_digits, count):
                    yield list(tpl)

        for combo in gen_slots():
            if len(combos) >= limit * 15:
                break
            if any(combo.count(n) > max_repeat for n in set(combo)):
                continue
            if len(set(combo)) < min(int(config.get("min_unique", 2)), count):
                continue
            key = tuple(combo)
            if key in seen:
                continue
            seen.add(key)
            sc, parts = score_combination(combo, per_draw)
            combos.append({
                "numbers": combo,
                "score": sc,
                "digits": parts,
                "is_strong": is_strong_recommendation(sc),
            })

        combos.sort(key=lambda c: -c["score"])
        return combos[:limit]

    def _fallback_combo(self, universe: list[str], count: int) -> list[str]:
        return random.sample(universe, min(count, len(universe)))

    def _score_fireball(
        self,
        per_bonus: list,
        per_draw: list,
        config: dict,
        main: list[str],
    ) -> dict:
        bmin = config.get("bonus_min")
        bmax = config.get("bonus_max")
        if bmin is None or bmax is None:
            return {}
        pad = int(config.get("pad", 1))
        universe = [_normalize(i, pad) for i in range(int(bmin), int(bmax) + 1)]
        flat_bonus = [b for draw in per_bonus for b in draw if b]
        if not flat_bonus and per_draw:
            flat_bonus = []
        from collections import Counter
        freq = Counter(flat_bonus)
        scored = []
        for n in universe:
            if n in set(main):
                continue
            s = freq.get(n, 0) * 10 + random.uniform(0, 5)
            scored.append((s, n))
        scored.sort(reverse=True)
        if not scored:
            n = random.choice(universe)
            return {"number": n, "score": 40, "label": "Fireball"}
        best = scored[0]
        return {
            "number": best[1],
            "score": min(99, int(best[0] * 3)),
            "label": "Fireball",
            "separate_from_main": True,
        }

    def _fireball_alternatives(self, primary: dict, config: dict, count: int = 3) -> list[dict]:
        bmin = config.get("bonus_min")
        bmax = config.get("bonus_max")
        if bmin is None:
            return []
        pad = int(config.get("pad", 1))
        universe = [_normalize(i, pad) for i in range(int(bmin), int(bmax) + 1)]
        primary_n = primary.get("number")
        alts = []
        for n in universe:
            if n != primary_n:
                alts.append({"number": n, "score": random.randint(35, 75)})
            if len(alts) >= count:
                break
        return alts
