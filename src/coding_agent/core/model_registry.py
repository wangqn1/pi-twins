from __future__ import annotations

from dataclasses import dataclass, field

from ai import Model


@dataclass
class ModelRegistry:
    models: list[Model] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.models:
            self.models = [Model(provider="mock", id="echo", api="mock", reasoning=False)]

    def register_model(self, model: Model) -> None:
        existing = self.find(model.provider, model.id)
        if existing is None:
            self.models.append(model)

    def find(self, provider: str, model_id: str) -> Model | None:
        for model in self.models:
            if model.provider == provider and model.id == model_id:
                return model
        return None

    def get_available(self) -> list[Model]:
        return list(self.models)

    def get_default_model(self) -> Model:
        return self.models[0]

