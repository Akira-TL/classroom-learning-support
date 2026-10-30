from dataclasses import dataclass

from .models import CountRatio, SupportMetrics


def ratio(numerator: int, denominator: int) -> CountRatio:
    return CountRatio(
        numerator=numerator, denominator=denominator, ratio=numerator / denominator if denominator else None
    )


@dataclass
class SupportCounts:
    generated: int = 0
    confirmed: int = 0
    adopted: int = 0

    def view(self) -> SupportMetrics:
        return SupportMetrics(
            generated_count=self.generated,
            confirmed_count=self.confirmed,
            adopted_count=self.adopted,
            confirmation_rate=ratio(self.confirmed, self.generated),
            adoption_rate=ratio(self.adopted, self.confirmed),
        )
