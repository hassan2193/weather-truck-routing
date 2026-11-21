"""Human-readable explanation of a recommendation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .engine import RankedRoute, ranking_key
from .metrics import RouteMetrics


@dataclass
class Recommendation:
    recommended: str
    headline: str
    details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    all_routes_unsafe: bool = False


def fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _mi(v: float) -> str:
    return f"{v:.1f} mi"


def build_recommendation(
    ranking: Sequence[RankedRoute], labels: Mapping[str, str]
) -> Recommendation:
    """Explain why ``ranking[0]`` won, using the first criterion that separates it from the runner-up."""
    best = ranking[0]
    name = labels[best.key]
    m = best.metrics
    rec = Recommendation(recommended=best.key, headline="")
    rec.all_routes_unsafe = all(r.metrics.has_no_travel for r in ranking)

    if m.coverage < 1.0:
        rec.warnings.append(
            f"Weather data covers {m.coverage * 100:.0f}% of {name}; the remaining distance "
            "(typically beyond the forecast horizon) is excluded from risk totals."
        )
    if m.assessed_miles <= 0:
        rec.headline = f"{name} is the fastest option, but no weather data was available to assess risk."
        rec.warnings.append("Weather risk could not be evaluated; ranking falls back to travel time only.")
        return rec

    if rec.all_routes_unsafe:
        rec.warnings.append(
            "Every route contains No Travel conditions for this load. Delay departure or reconsider the trip."
        )

    if len(ranking) == 1:
        rec.headline = f"{name} is the only route the routing service returned."
        rec.details.append(_exposure_sentence(name, m))
        return rec

    runner = ranking[1]
    other_name, o = labels[runner.key], runner.metrics
    reasons = _reasons(m, o, other_name)
    unsafe_others = [labels[r.key] for r in ranking[1:] if r.metrics.has_no_travel]

    if rec.all_routes_unsafe:
        lead = "has the least No Travel exposure" if m.no_travel_miles < o.no_travel_miles else "ranks best overall"
        rec.headline = f"{name} is the least-bad option: {lead}, but it is still unsafe."
    elif unsafe_others and not m.has_no_travel and not reasons.get("severe_miles"):
        rec.headline = (
            f"{name} is recommended because it avoids No Travel conditions that affect {_join(unsafe_others)}."
        )
    else:
        rec.headline = _headline(name, reasons, other_name, m, o)

    if unsafe_others and not m.has_no_travel:
        rec.details.append(f"{_join(unsafe_others)} cross No Travel conditions and are flagged unsafe.")
    rec.details.append(_exposure_sentence(name, m))
    if m.duration_s > o.duration_s + 30:
        rec.details.append(
            f"{name} takes {fmt_duration(m.duration_s - o.duration_s)} longer than {other_name}; "
            "weather risk is weighted above travel time."
        )
    return rec


def _reasons(w: RouteMetrics, o: RouteMetrics, other: str) -> dict[str, str]:
    """Phrases for every criterion where the winner is strictly better than the runner-up."""
    out: dict[str, str] = {}
    wk, ok = ranking_key(w), ranking_key(o)
    if wk[2] < ok[2]:
        out["severe_miles"] = f"fewer severe-weather miles ({_mi(w.severe_miles)} vs {_mi(o.severe_miles)} on {other})"
    if wk[3] < ok[3]:
        out["high_miles"] = f"fewer high-risk miles ({_mi(w.high_miles)} vs {_mi(o.high_miles)} on {other})"
    if wk[4] < ok[4]:
        out["average_risk"] = (
            f"lower overall weather exposure (avg risk {w.average_risk:.2f} vs "
            f"{'n/a' if o.average_risk is None else format(o.average_risk, '.2f')} on {other})"
        )
    if wk[5] < ok[5]:
        out["duration"] = (
            f"a shorter travel time ({fmt_duration(w.duration_s)} vs {fmt_duration(o.duration_s)} on {other})"
        )
    return out


def _headline(name: str, reasons: dict[str, str], other: str, w: RouteMetrics, o: RouteMetrics) -> str:
    # Keep priority order; lead with the deciding (first) criterion.
    phrases = [reasons[c] for c in ("severe_miles", "high_miles", "average_risk", "duration") if c in reasons]
    if not phrases:
        return f"{name} is recommended; it is equivalent to the alternatives on every criterion."
    if "duration" in reasons and len(phrases) == 1:
        return (
            f"{name} is recommended: weather exposure is the same as {other}, "
            f"and it has {phrases[0]}."
        )
    return f"{name} is recommended because it has {_join(phrases[:3])}."


def _exposure_sentence(name: str, m: RouteMetrics) -> str:
    if m.average_risk is None:
        return f"{name}: no weather data available."
    parts = [f"{_mi(m.severe_miles)} severe", f"{_mi(m.high_miles)} high", f"{_mi(m.moderate_miles)} moderate"]
    text = f"{name} exposure: {', '.join(parts)} of {_mi(m.distance_mi)} (avg risk {m.average_risk:.2f} / 4)"
    if m.has_no_travel:
        text += f"; {_mi(m.no_travel_miles)} under No Travel conditions"
    return text + "."


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]
