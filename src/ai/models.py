# ===========================
# Author: wqn
# Email: wangqn@tellhow.com
# Created: 20260320
# ===========================

from __future__ import annotations

from .types import Model, Usage


def calculate_cost(model: Model, usage: Usage) -> dict[str, float]:
    usage.cost.input = (model.cost.input / 1_000_000) * usage.input
    usage.cost.output = (model.cost.output / 1_000_000) * usage.output
    usage.cost.cache_read = (model.cost.cache_read / 1_000_000) * usage.cache_read
    usage.cost.cache_write = (model.cost.cache_write / 1_000_000) * usage.cache_write
    usage.cost.total = usage.cost.input + usage.cost.output + usage.cost.cache_read + usage.cost.cache_write
    return usage.cost.to_dict()


def supports_xhigh(model: Model) -> bool:
    if "gpt-5.2" in model.id or "gpt-5.3" in model.id or "gpt-5.4" in model.id:
        return True
    if model.api == "anthropic-messages":
        return "opus-4-6" in model.id or "opus-4.6" in model.id
    return False
