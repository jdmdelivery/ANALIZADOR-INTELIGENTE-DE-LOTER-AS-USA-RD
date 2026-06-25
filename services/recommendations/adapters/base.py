"""Adaptador base."""
from __future__ import annotations

from abc import ABC, abstractmethod

from services.recommendations.constants import (
    INSUFFICIENT_HISTORY_MSG,
    MIN_HISTORY,
    RECOMMENDATION_DISCLAIMER,
)


class BaseAdapter(ABC):
    adapter_key: str = "base"
    game_type_label: str = "Juego"

    @abstractmethod
    def recommend(self, ctx: dict, config: dict) -> dict:
        ...

    def insufficient(self, ctx: dict, count: int) -> dict:
        return {
            "ok": False,
            "message": INSUFFICIENT_HISTORY_MSG,
            "history_count": count,
            "min_required": MIN_HISTORY,
            "disclaimer": RECOMMENDATION_DISCLAIMER,
        }

    def base_meta(self, ctx: dict, config: dict, family: str) -> dict:
        lot = ctx["lottery"]
        return {
            "country": lot.get("country"),
            "lottery": lot.get("name"),
            "lottery_id": lot.get("id"),
            "draw_name": ctx.get("draw_name"),
            "game_family": family,
            "game_type": self.game_type_label,
            "adapter": self.adapter_key,
            "latest_result_date": ctx.get("latest_result_date"),
            "history_count": ctx.get("total_results", 0),
            "disclaimer": RECOMMENDATION_DISCLAIMER,
        }
