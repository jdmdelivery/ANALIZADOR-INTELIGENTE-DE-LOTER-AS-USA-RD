"""Powerball y Mega Millions — principales y bola especial separadas."""
from __future__ import annotations

import random
from collections import Counter

from services.recommendations.adapters.lotto_adapter import LottoAdapter
from services.recommendations.constants import BONUS_LABELS, MIN_HISTORY
from services.recommendations.scoring import confidence_from_score, is_strong_recommendation, score_number


class PowerMegaAdapter(LottoAdapter):
    adapter_key = "power_mega"
    game_type_label = "Powerball / Mega Millions"

    def recommend(self, ctx: dict, config: dict) -> dict:
        base = super().recommend(ctx, config)
        if not base.get("ok"):
            return base

        per_draw = ctx["per_draw_main"]
        per_bonus = ctx.get("per_draw_bonus") or []
        lot_type = ctx["lottery"].get("type", "powerball")
        bonus_label = BONUS_LABELS.get(lot_type, "Bola especial")

        bonus_ball = self._pick_special_ball(per_bonus, config, base["generated_numbers"])
        bonus_score = bonus_ball.get("score", 0)
        main_score = base.get("score", 0)

        base["bonus_label"] = bonus_label
        base["generated_bonus"] = bonus_ball.get("number")
        base["bonus_numbers"] = [bonus_ball["number"]] if bonus_ball.get("number") else []
        base["special_ball"] = bonus_ball
        base["main_score"] = main_score
        base["special_ball_score"] = bonus_score
        base["game_type"] = self.game_type_label
        base["analysis_text"] = (
            f"Principales (score {main_score}): {', '.join(base['generated_numbers'])}. "
            f"{bonus_label} (score {bonus_score}): {bonus_ball.get('number', '—')} — "
            "analizados por separado, sin mezclar."
        )
        combined = round((main_score * 0.85) + (bonus_score * 0.15))
        base["score"] = combined
        conf_key, conf_label = confidence_from_score(combined)
        base["confidence_level"] = conf_key
        base["confidence_label"] = conf_label
        base["is_strong_recommendation"] = is_strong_recommendation(combined)
        return base

    def _pick_special_ball(
        self,
        per_bonus: list,
        config: dict,
        mains: list[str],
    ) -> dict:
        bmin = int(config.get("bonus_min", 1))
        bmax = int(config.get("bonus_max", 26))
        pad = 2
        universe = [str(i).zfill(pad) for i in range(bmin, bmax + 1)]
        flat = [b for draw in per_bonus for b in draw if b]
        freq = Counter(flat)
        scored = []
        main_set = set(mains)
        for n in universe:
            if n in main_set:
                continue
            s, _ = score_number(n, [[b] for b in flat] if flat else [[n]])
            s += freq.get(n, 0) * 8
            scored.append((s, n))
        scored.sort(reverse=True)
        if scored:
            return {"number": scored[0][1], "score": int(scored[0][0]), "separate_from_main": True}
        n = random.choice(universe)
        return {"number": n, "score": 45, "separate_from_main": True}
