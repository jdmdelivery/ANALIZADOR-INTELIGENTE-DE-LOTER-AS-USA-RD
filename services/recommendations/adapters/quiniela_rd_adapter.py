"""Quiniela RD 00–99 — Top 10/20/50, posiciones 1ra/2da/3ra."""
from __future__ import annotations

from collections import Counter

from services.recommendations.adapters.base import BaseAdapter
from services.recommendations.categories import (
    build_hot_cold_lists,
    position_frequency,
)
from services.recommendations.constants import ANALYSIS_WINDOWS, MIN_HISTORY, STRONG_RECOMMENDATION_MIN
from services.recommendations.profile_builder import build_scored_profiles
from services.recommendations.scoring import (
    confidence_from_score,
    is_strong_recommendation,
    score_combination,
)


def _normalize(n: str, pad: int = 2) -> str:
    return str(int(str(n).lstrip("0") or "0")).zfill(pad)


class QuinielaRDAdapter(BaseAdapter):
    adapter_key = "quiniela_rd"
    game_type_label = "Quiniela RD 00–99"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        dates = ctx.get("dates") or []
        draw_name = ctx.get("draw_name") or ""
        min_req = int(ctx.get("effective_min_history") or MIN_HISTORY)
        if len(per_draw) < min_req:
            return self.insufficient(ctx, len(per_draw))

        pad = int(config.get("pad", 2))
        lo, hi = int(config["min"]), int(config["max"])
        universe = [_normalize(i, pad) for i in range(lo, hi + 1)]
        count = int(config.get("count", 3))
        weights = ctx.get("weights")
        pos_freq = position_frequency(per_draw, 100)

        profiles, categories = build_scored_profiles(
            universe,
            per_draw,
            pad=pad,
            weights=weights,
            dates=dates,
            draw_name=draw_name,
            position_freq=pos_freq,
        )

        scored_list = sorted(profiles.values(), key=lambda x: (-x["score"], x["number"]))
        top10 = scored_list[:10]
        top20 = scored_list[:20]
        top50 = scored_list[:50]

        hot, cold = build_hot_cold_lists(profiles, categories)
        overdue = sorted(
            [p for p in scored_list if p["category"] in ("atrasado", "caliente_atrasado")],
            key=lambda p: -p.get("draws_since", 0),
        )[:10]

        primary = self._pick_primary_combo(scored_list, count, per_draw, pos_freq)
        combo_score, digit_parts = score_combination(
            primary,
            per_draw,
            weights=weights,
            position_freq=pos_freq,
            dates=dates,
            draw_name=draw_name,
        )
        for i, part in enumerate(digit_parts):
            n = part["number"]
            part["reason"] = profiles.get(n, {}).get("reason", "")
            part["position"] = i + 1

        conf_key, conf_label = confidence_from_score(combo_score)
        strong = is_strong_recommendation(combo_score)

        analysis_text = ". ".join(
            profiles.get(n, {}).get("reason", "") for n in primary[:3] if profiles.get(n)
        )
        if not strong:
            analysis_text = f"Confianza baja (score {combo_score}). {analysis_text}"

        position_picks = []
        for pos in range(3):
            pos_scored = []
            for p in scored_list:
                pf = pos_freq.get(pos)
                if not pf:
                    continue
                mx = max(pf.values()) if pf else 1
                pos_score = int((pf.get(p["number"], 0) / mx) * 100) if mx else p["score"]
                pos_scored.append({**p, "position_score": pos_score})
            pos_scored.sort(key=lambda x: (-x["position_score"], x["number"]))
            position_picks.append({
                "position": pos + 1,
                "label": f"Posición {pos + 1}",
                "top_5": [
                    {
                        "number": x["number"],
                        "score": x["position_score"],
                        "reason": x["reason"],
                    }
                    for x in pos_scored[:5]
                ],
            })

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
            "analysis_basis": "Basado en frecuencia 7/15/25/100, posición, día de semana y tendencia",
            "digit_scores": digit_parts,
            "position_picks": position_picks,
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
            "windows": {str(w): len(per_draw[:w]) for w in ANALYSIS_WINDOWS},
            "total_results": len(per_draw),
            "analysis_window": len(per_draw),
            "selection_method": "multi_window_position_blend",
        }

    def _pick_primary_combo(
        self,
        scored: list[dict],
        count: int,
        per_draw: list,
        pos_freq: dict[int, Counter] | None = None,
    ) -> list[str]:
        """Mezcla score global + frecuencia por posición; evita repetir último sorteo."""
        last = set(per_draw[0]) if per_draw else set()
        scored_map = {p["number"]: p for p in scored}
        chosen: list[str] = []

        def _key(n) -> str:
            z = _normalize(str(n), 2)
            return z if z in scored_map else str(n)

        if pos_freq and count <= 3:
            for pos in range(count):
                pf = pos_freq.get(pos) or Counter()
                ranked = sorted(
                    pf.keys(),
                    key=lambda n: (
                        -pf.get(n, 0),
                        -scored_map.get(_key(n), {}).get("score", 0),
                        _key(n),
                    ),
                )
                picked = None
                for n in ranked:
                    kn = _key(n)
                    if kn not in chosen and kn not in last:
                        picked = kn
                        break
                if not picked:
                    for p in scored:
                        if p["number"] not in chosen and p["number"] not in last:
                            picked = p["number"]
                            break
                if picked:
                    chosen.append(picked)

        if len(chosen) < count:
            pool = [p["number"] for p in scored if p["number"] not in chosen and p["number"] not in last]
            if len(pool) < count - len(chosen):
                pool = [p["number"] for p in scored if p["number"] not in chosen]
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
