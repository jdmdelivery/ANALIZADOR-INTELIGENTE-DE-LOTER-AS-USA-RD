"""Quiniela RD 00–99 — Top 10/20/50, posiciones 1ra/2da/3ra."""
from __future__ import annotations

import random
from itertools import combinations

from services.recommendations.adapters.base import BaseAdapter
from services.recommendations.categories import (
    assign_category,
    build_hot_cold_lists,
    category_explanation,
    category_label,
    classify_number,
    position_frequency,
)
from services.recommendations.constants import MIN_HISTORY, STRONG_RECOMMENDATION_MIN
from services.recommendations.scoring import (
    confidence_from_score,
    format_score_breakdown,
    is_strong_recommendation,
    score_combination,
    score_number,
)


def _normalize(n: str, pad: int = 2) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(pad)


class QuinielaRDAdapter(BaseAdapter):
    adapter_key = "quiniela_rd"
    game_type_label = "Quiniela RD 00–99"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        if len(per_draw) < MIN_HISTORY:
            return self.insufficient(ctx, len(per_draw))

        pad = int(config.get("pad", 2))
        lo, hi = int(config["min"]), int(config["max"])
        universe = [_normalize(i, pad) for i in range(lo, hi + 1)]
        count = int(config.get("count", 3))

        profiles: dict[str, dict] = {}
        categories: dict[str, str] = {}
        scored_list: list[dict] = []

        pos_freq = position_frequency(per_draw, 100)
        weights = ctx.get("weights")

        for num in universe:
            prof = classify_number(num, per_draw, pad=pad, window=25, universe=universe)
            cat = assign_category(prof)
            categories[num] = cat
            s, sexp = score_number(num, per_draw, weights=weights, position_freq=pos_freq)
            profiles[num] = {
                **prof,
                "category": cat,
                "category_label": category_label(cat),
                "score": s,
                "reason": category_explanation(cat, prof),
                "score_breakdown": format_score_breakdown(sexp),
            }
            scored_list.append(profiles[num])

        scored_list.sort(key=lambda x: (-x["score"], x["number"]))
        top10 = scored_list[:10]
        top20 = scored_list[:20]
        top50 = scored_list[:50]

        hot, cold = build_hot_cold_lists(profiles, categories)
        overdue = sorted(
            [p for p in scored_list if p["category"] in ("atrasado", "caliente_atrasado")],
            key=lambda p: -p.get("draws_since", 0),
        )[:10]

        primary = self._pick_primary_combo(scored_list, count, per_draw)
        combo_score, digit_parts = score_combination(
            primary, per_draw, weights=weights, position_freq=pos_freq
        )
        conf_key, conf_label = confidence_from_score(combo_score)
        strong = is_strong_recommendation(combo_score)

        analysis_text = ". ".join(
            category_explanation(profiles[n]["category"], profiles[n]) for n in primary[:3]
        )
        if not strong:
            analysis_text = f"Confianza baja (score {combo_score}). {analysis_text}"

        meta = self.base_meta(ctx, config, "quiniela_rd")
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
            "analysis_text": analysis_text + ".",
            "analysis_basis": "Basado en frecuencia 7/15/25/100, posición y tendencia",
            "digit_scores": digit_parts,
            "top_numbers": {
                "top_10": top10,
                "top_20": top20,
                "top_50": top50,
            },
            "hot_numbers": [p["number"] for p in hot],
            "cold_numbers": [p["number"] for p in cold],
            "overdue_numbers": [p["number"] for p in overdue],
            "hot_numbers_detail": hot,
            "cold_numbers_detail": cold,
            "overdue_numbers_detail": overdue,
            "number_profiles": profiles,
            "position_frequency": {k: dict(v) for k, v in pos_freq.items()},
            "windows": {
                "7": len(per_draw[:7]),
                "15": len(per_draw[:15]),
                "30": len(per_draw[:30]),
                "100": len(per_draw[:100]),
            },
            "total_results": len(per_draw),
            "analysis_window": 25,
        }

    def _pick_primary_combo(self, scored: list[dict], count: int, per_draw: list) -> list[str]:
        last = set(per_draw[0]) if per_draw else set()
        pool = [p["number"] for p in scored if p["number"] not in last]
        if len(pool) < count:
            pool = [p["number"] for p in scored]
        chosen: list[str] = []
        for n in pool:
            if n not in chosen:
                chosen.append(n)
            if len(chosen) >= count:
                break
        if len(chosen) < count:
            for p in scored:
                if p["number"] not in chosen:
                    chosen.append(p["number"])
                if len(chosen) >= count:
                    break
        return chosen[:count]
