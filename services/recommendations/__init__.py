"""Motor inteligente de recomendaciones — USA y RD separados por adaptador."""
from services.recommendations.engine import (
    analyze_lottery,
    build_analysis_stats,
    generate_recommendation,
)
from services.recommendations.paste_analyzer import analyze_pasted_numbers
from services.recommendations.backtesting import run_backtest_summary
from services.recommendations.weight_tuner import tune_weights_from_backtests

__all__ = [
    "analyze_lottery",
    "build_analysis_stats",
    "generate_recommendation",
    "analyze_pasted_numbers",
    "run_backtest_summary",
    "tune_weights_from_backtests",
]
