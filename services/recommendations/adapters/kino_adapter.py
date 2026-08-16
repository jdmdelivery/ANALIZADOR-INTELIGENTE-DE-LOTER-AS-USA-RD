"""Kino / Super Kino / Pick 10 — lista sugerida y comparador."""
from __future__ import annotations

from services.recommendations.adapters.lotto_adapter import LottoAdapter
from services.recommendations.constants import MIN_HISTORY
from services.recommendations.scoring import (
    build_scoring_cache,
    confidence_from_score,
    is_strong_recommendation,
    score_combination,
    score_number,
)


def _sanitize_kino_numbers(numbers: list, config: dict) -> list[str]:
    """Únicos, en rango, ordenados por score (entrada ya ordenada)."""
    count = int(config.get("count", 20))
    pad = int(config.get("pad", 2))
    lo, hi = int(config["min"]), int(config["max"])
    seen: set[str] = set()
    clean: list[str] = []
    for n in numbers or []:
        try:
            v = int(str(n).lstrip("0") or "0")
        except (TypeError, ValueError):
            continue
        if v < lo or v > hi:
            continue
        key = str(v).zfill(pad)
        if key in seen:
            continue
        seen.add(key)
        clean.append(key)
        if len(clean) >= count:
            break
    return clean


class KinoAdapter(LottoAdapter):
    adapter_key = "kino"
    game_type_label = "Kino / Super Kino"

    def recommend(self, ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        if len(per_draw) < MIN_HISTORY:
            return self.insufficient(ctx, len(per_draw))

        base = self.base_meta(ctx, config, "kino")
        count = int(config.get("count", 20))
        pad = int(config.get("pad", 2))
        lo, hi = int(config["min"]), int(config["max"])
        universe = [str(i).zfill(pad) for i in range(lo, hi + 1)]
        weights = ctx.get("weights")
        score_cache = build_scoring_cache(per_draw, weights=weights, draw_name="")

        scored_nums = []
        for n in universe:
            s, _ = score_number(
                n,
                per_draw,
                weights=weights,
                scoring_cache=score_cache,
            )
            scored_nums.append({"number": n, "score": s})
        scored_nums.sort(key=lambda x: (-x["score"], x["number"]))

        last = set(per_draw[0]) if per_draw else set()
        pool_scored = [x for x in scored_nums if x["number"] not in last]
        if len(pool_scored) < count:
            pool_scored = scored_nums
        suggested = _sanitize_kino_numbers(
            [x["number"] for x in pool_scored[: count + 10]],
            config,
        )
        if len(suggested) < count:
            extra = _sanitize_kino_numbers(
                [x["number"] for x in scored_nums],
                {**config, "count": count},
            )
            for n in extra:
                if n not in suggested:
                    suggested.append(n)
                if len(suggested) >= count:
                    break

        combo_score, digit_parts = score_combination(
            suggested,
            per_draw,
            weights=weights,
        )
        conf_key, conf_label = confidence_from_score(combo_score)
        hot_detail = [
            {
                "number": part["number"],
                "score": part["score"],
                "category": "caliente",
                "category_label": "Caliente",
            }
            for part in scored_nums[:10]
        ]
        cold_detail = [
            {
                "number": part["number"],
                "score": part["score"],
                "category": "frío",
                "category_label": "Frío",
            }
            for part in scored_nums[-10:]
        ]

        base["generated_numbers"] = suggested
        base["ok"] = True
        base["numbers"] = suggested
        base["recommended_numbers"] = suggested
        base["all_unique"] = len(set(suggested)) == len(suggested)
        base["in_range"] = all(
            lo <= int(n) <= hi for n in suggested
        ) if suggested else False
        base["recommend_count"] = len(suggested)
        if config.get("numbers_per_draw"):
            base["numbers_per_draw"] = int(config["numbers_per_draw"])
        if "strict_score_ranking" in config:
            base["strict_score_ranking"] = bool(config.get("strict_score_ranking"))
        base["score"] = combo_score
        base["confidence_level"] = conf_key
        base["confidence_label"] = conf_label
        base["is_strong_recommendation"] = is_strong_recommendation(combo_score)
        base["digit_scores"] = digit_parts
        base["suggested_list"] = scored_nums[:count]
        base["top_numbers"] = {
            "top_10": scored_nums[:10],
            "top_20": scored_nums[:20],
            "top_50": scored_nums[:50],
        }
        base["top_combinations"] = {"top_5": [], "top_10": [], "top_20": []}
        base["suggested_combinations"] = []
        base["hot_numbers"] = [p["number"] for p in hot_detail]
        base["cold_numbers"] = [p["number"] for p in cold_detail]
        base["hot_numbers_detail"] = hot_detail
        base["cold_numbers_detail"] = cold_detail
        base["total_results"] = len(per_draw)
        base["analysis_window"] = 25
        base["game_type"] = self.game_type_label
        base["payout_table_available"] = False
        base["analysis_text"] = (
            f"Lista sugerida de {count} números según score histórico. "
            "Tabla de pagos no configurada — sin premio estimado."
        )
        return base

    def compare_user_list(self, user_numbers: list[str], ctx: dict, config: dict) -> dict:
        per_draw = ctx["per_draw_main"]
        if not per_draw:
            return {"ok": False, "message": "Sin histórico"}
        pad = int(config.get("pad", 2))
        normalized = [str(int(str(n).lstrip("0") or "0")).zfill(pad) for n in user_numbers]
        last = per_draw[0]
        hits_exact = len(set(normalized) & set(last))
        hits_any = sum(1 for n in normalized if n in last)
        match_pct = round((hits_any / max(len(normalized), 1)) * 100, 1)
        per_num = []
        for n in normalized:
            s, _ = score_number(n, per_draw)
            per_num.append({"number": n, "score": s, "in_last_draw": n in last})
        return {
            "ok": True,
            "user_numbers": normalized,
            "hits_exact_last_draw": hits_exact,
            "hits_any_last_draw": hits_any,
            "match_percent": match_pct,
            "number_analysis": per_num,
        }
