"""Kino / Super Kino / Pick 10 — lista sugerida y comparador."""
from __future__ import annotations

import random

from services.recommendations.adapters.lotto_adapter import LottoAdapter
from services.recommendations.constants import MIN_HISTORY
from services.recommendations.scoring import score_number


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
        base = super().recommend(ctx, config)
        if not base.get("ok"):
            return base

        per_draw = ctx["per_draw_main"]
        count = int(config.get("count", 20))
        pad = int(config.get("pad", 2))
        lo, hi = int(config["min"]), int(config["max"])
        universe = [str(i).zfill(pad) for i in range(lo, hi + 1)]
        weights = ctx.get("weights")

        scored_nums = []
        for n in universe:
            s, _ = score_number(n, per_draw, weights=weights)
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
        base["generated_numbers"] = suggested
        base["numbers"] = suggested
        base["recommended_numbers"] = suggested
        base["all_unique"] = len(set(suggested)) == len(suggested)
        base["in_range"] = all(
            lo <= int(n) <= hi for n in suggested
        ) if suggested else False
        base["recommend_count"] = len(suggested)
        base["suggested_list"] = scored_nums[:count]
        base["top_numbers"] = {
            "top_10": scored_nums[:10],
            "top_20": scored_nums[:20],
            "top_50": scored_nums[:50],
        }
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
