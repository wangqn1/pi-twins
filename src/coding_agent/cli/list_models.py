from __future__ import annotations

from ai import Model
from tui import fuzzy_filter

from ..core.model_registry import ModelRegistry


def format_token_count(count: int) -> str:
    if count >= 1_000_000:
        millions = count / 1_000_000
        return f"{millions:.1f}M" if millions % 1 else f"{int(millions)}M"
    if count >= 1_000:
        thousands = count / 1_000
        return f"{thousands:.1f}K" if thousands % 1 else f"{int(thousands)}K"
    return str(count)


def render_models(model_registry: ModelRegistry, search_pattern: str | None = None) -> str:
    models = model_registry.get_available()
    if not models:
        return "No models available."

    filtered_models: list[Model] = list(models)
    if search_pattern:
        filtered_models = fuzzy_filter(filtered_models, search_pattern, lambda model: f"{model.provider} {model.id}")

    if not filtered_models:
        return f'No models matching "{search_pattern}"'

    filtered_models.sort(key=lambda model: (model.provider, model.id))
    rows = [
        {
            "provider": model.provider,
            "model": model.id,
            "context": format_token_count(int(model.context_window)),
            "max_out": format_token_count(int(model.max_tokens)),
            "thinking": "yes" if model.reasoning else "no",
            "images": "yes" if "image" in model.input else "no",
        }
        for model in filtered_models
    ]
    headers = {
        "provider": "provider",
        "model": "model",
        "context": "context",
        "max_out": "max-out",
        "thinking": "thinking",
        "images": "images",
    }
    widths = {
        "provider": max(headers["provider"].__len__(), *(row["provider"].__len__() for row in rows)),
        "model": max(headers["model"].__len__(), *(row["model"].__len__() for row in rows)),
        "context": max(headers["context"].__len__(), *(row["context"].__len__() for row in rows)),
        "max_out": max(headers["max_out"].__len__(), *(row["max_out"].__len__() for row in rows)),
        "thinking": max(headers["thinking"].__len__(), *(row["thinking"].__len__() for row in rows)),
        "images": max(headers["images"].__len__(), *(row["images"].__len__() for row in rows)),
    }

    lines = [
        "  ".join(
            [
                headers["provider"].ljust(widths["provider"]),
                headers["model"].ljust(widths["model"]),
                headers["context"].ljust(widths["context"]),
                headers["max_out"].ljust(widths["max_out"]),
                headers["thinking"].ljust(widths["thinking"]),
                headers["images"].ljust(widths["images"]),
            ]
        )
    ]
    for row in rows:
        lines.append(
            "  ".join(
                [
                    row["provider"].ljust(widths["provider"]),
                    row["model"].ljust(widths["model"]),
                    row["context"].ljust(widths["context"]),
                    row["max_out"].ljust(widths["max_out"]),
                    row["thinking"].ljust(widths["thinking"]),
                    row["images"].ljust(widths["images"]),
                ]
            )
        )
    return "\n".join(lines)
