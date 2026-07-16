from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class OnlyFactorId:
    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("factor_id is required")
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value
