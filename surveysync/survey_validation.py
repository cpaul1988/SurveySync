"""Strict numeric and header contracts; source PointIDs are never normalized."""
import math
import re


def finite_number(value, field="Measurement") -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number.")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number.")
    return number


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(value or "").lstrip("\ufeff")).casefold()


def unit_factor(unit: str) -> float:
    factors = {"meters": 1.0, "international_feet": 0.3048, "us_survey_feet": 1200 / 3937}
    if unit not in factors:
        raise ValueError(f"Unsupported declared survey unit: {unit!r}.")
    return factors[unit]
