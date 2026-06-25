"""Lucky Day, Loto Más, Loto Pool — multi-número sin repetir, Top 5/10/20."""
from __future__ import annotations

import random
from itertools import combinations

from services.recommendations.adapters.base import BaseAdapter
from services.recommendations.categories import build_hot_cold_lists
from services.recommendations.constants import MIN_HISTORY, STRONG_RECOMMENDATION_MIN
from services.recommendations.profile_builder import build_scored_profiles
from services.recommendations.scoring import (
    confidence_from_score,
    is_strong_recommendation,
    score_combination,
)


def _normalize(n: str, pad: int = 2) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(pad)


class LottoAdapter(BaseAdapter):
    adapter_key = "lotto"
    game_type_label = "Lotto multi-número"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        dates = ctx.get("dates") or []
        draw_name = ctx.get("draw_name") or ""
        if len(per_draw) < MIN_HISTORY:
            return self.insufficient(ctx, len(per_draw))

        pad = int(config.get("pad", 2))
        count = int(config["count"])
        lo, hi = int(config["min"]), int(config["max"])
        allow_repeat = bool(config.get("allow_repeat", False))
        universe = [_normalize(i, pad) for i in range(lo, hi + 1)]
        weights = ctx.get("weights")

        profiles, categories = build_scored_profiles(
            universe,
            per_draw,
            pad=pad,
            weights=weights,
            dates=dates,
            draw_name=draw_name,
        )

        scored = sorted(profiles.values(), key=lambda x: (-x["score"], x["number"]))
        hot, cold = build_hot_cold_lists(profiles, categories)

        top5 = self._top_combos(scored, count, per_draw, allow_repeat, 5, weights, dates, draw_name)
        top10 = self._top_combos(scored, count, per_draw, allow_repeat, 10, weights, dates, draw_name)
        top20 = self._top_combos(scored, count, per_draw, allow_repeat, 20, weights, dates, draw_name)

        primary = top5[0]["numbers"] if top5 else self._fallback_primary(scored, count, per_draw, allow_repeat, universe)
        combo_score = top5[0]["score"] if top5 else 0
        _, digit_parts = score_combination(
            primary, per_draw, weights=weights, dates=dates, draw_name=draw_name
        )
        for part in digit_parts:
            part["reason"] = profiles.get(part["number"], {}).get("reason", "")

        conf_key, conf_label = confidence_from_score(combo_score)

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
            "top_combinations": {"top_5": top5, "top_10": top10, "top_20": top20},
            "suggested_combinations": top5,
            "hot_numbers": [p["number"] for p in hot],
            "cold_numbers": [p["number"] for p in cold],
            "hot_numbers_detail": hot,
            "cold_numbers_detail": cold,
            "total_results": len(per_draw),
            "analysis_window": 25,
        }

    def _top_combos(
        self,
        scored: list[dict],
        count: int,
        per_draw: list,
        allow_repeat: bool,
        limit: int,
        weights: dict | None,
        dates: list[str],
        draw_name: str,
    ) -> list[dict]:
        pool = [p["number"] for p in scored[: min(14, len(scored))]]
        if len(pool) < count:
            return []

        combos: list[dict] = []
        seen: set[tuple] = set()
        for combo in combinations(pool, count):
            key = tuple(sorted(combo))
            if key in seen:
                continue
            seen.add(key)
            sc, parts = score_combination(
                list(combo), per_draw, weights=weights, dates=dates, draw_name=draw_name
            )
            conf_key, conf_label = confidence_from_score(sc)
            combos.append({
                "numbers": list(combo),
                "score": sc,
                "confidence_level": conf_key,
                "confidence_label": conf_label,
                "digits": parts,
                "is_strong": is_strong_recommendation(sc),
            })
            if len(combos) >= limit * 40:
                break

        combos.sort(key=lambda c: -c["score"])
        return combos[:limit]

    def _fallback_primary(
        self,
        scored: list[dict],
        count: int,
        per_draw: list,
        allow_repeat: bool,
        universe: list[str],
    ) -> list[str]:
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
        return primary[:count]
