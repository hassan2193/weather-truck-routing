"""Risk level definitions shared by the whole backend."""
from __future__ import annotations

from enum import IntEnum


class RiskLevel(IntEnum):
    """Ordered weather risk categories: Low < Moderate < High < Severe < No Travel.

    The integer value doubles as the numeric *risk score* used for averages.
    """

    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def slug(self) -> str:
        return self.name.lower()


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}
