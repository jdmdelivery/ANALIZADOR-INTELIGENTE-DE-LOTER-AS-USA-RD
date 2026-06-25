"""Lucky Day, Loto Más, Loto Pool — multi-número sin repetir."""
from __future__ import annotations

import random

from services.recommendations.adapters.base import BaseAdapter
from services.recommendations.categories import (
    assign_category,
    build_hot_cold_lists,
    category_explanation,
    category_label,
    classify_number,
)
from services.recommendations.constants import MIN_HISTORY
from services.recommendations.scoring import (
    confidence_from_score,
    is_strong_recommendation,
    score_combination,
    score_number,
)


def _normalize(n: str, pad: int = 2) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(pad)


class LottoAdapter(BaseAdapter):
    adapter_key = "lotto"
    game_type_label = "Lotto multi-número"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        if len(per_draw) < MIN_HISTORY:
            return self.insufficient(ctx, len(per_draw))

        pad = int(config.get("pad", 2))
        count = int(config["count"])
        lo, hi = int(config["min"]), int(config["max"])
        allow_repeat = bool(config.get("allow_repeat", False))
        universe = [_normalize(i, pad) for i in range(lo, hi + 1)]
        weights = ctx.get("weights")

        profiles: dict[str, dict] = {}
        categories: dict[str, str] = {}
        scored: list[dict] = []
        for num in universe:
            prof = classify_number(num, per_draw, pad=pad, window=25)
            cat = assign_category(prof)
            categories[num] = cat
            s, _ = score_number(num, per_draw, weights=weights)
            profiles[num] = {
                **prof,
                "category": cat,
                "category_label": category_label(cat),
                "score": s,
                "reason": category_explanation(cat, prof),
            }
            scored.append(profiles[num])
        scored.sort(key=lambda x: (-x["score"], x["number"]))

        last = set(per_draw[0]) if per_draw else set()
        pool = [p["number"] for p in scored if p["number"] not in last]
        if len(pool) < count:
            pool = [p["number"] for p in scored]

        primary: list[str] = []
        for n in pool:
            if not allow_repeat and n in primary:
                continue
            primary.append(n)
            if len(primary) >= count:
                break
        while len(primary) < count and universe:
            n = random.choice(universe)
            if allow_repeat or n not in primary:
                primary.append(n)

        combo_score, digit_parts = score_combination(primary, per_draw, weights=weights)
        conf_key, conf_label = confidence_from_score(combo_score)
        hot, cold = build_hot_cold_lists(profiles, categories)

        meta = self.base_meta(ctx, config, "lotto")
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
            "is_strong_recommendation": is_strong_recommendation(combo_score),
            "analysis_text": ". ".join(profiles[n]["reason"] for n in primary[:3]) + ".",
            "digit_scores": digit_parts,
            "suggested_combinations": [{"numbers": primary, "score": combo_score}],
            "hot_numbers": [p["number"] for p in hot],
            "cold_numbers": [p["number"] for p in cold],
            "hot_numbers_detail": hot,
            "cold_numbers_detail": cold,
            "total_results": len(per_draw),
            "analysis_window": 25,
        }
