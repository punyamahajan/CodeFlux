"""Convert length, weight, and temperature values between units."""

# Factors to a base unit: metres for length, grams for weight.
LENGTH = {"m": 1.0, "km": 1000.0, "mi": 1609.344}
WEIGHT = {"g": 1.0, "kg": 1000.0, "lb": 453.59237}
TEMPERATURE = ("C", "F", "K")


def _scale(value: float, from_unit: str, to_unit: str, factors: dict[str, float], kind: str) -> float:
    for unit in (from_unit, to_unit):
        if unit not in factors:
            raise ValueError(f"unknown {kind} unit '{unit}' (use one of: {', '.join(factors)})")
    return value * factors[from_unit] / factors[to_unit]


def convert_length(value: float, from_unit: str, to_unit: str) -> float:
    return _scale(value, from_unit, to_unit, LENGTH, "length")


def convert_weight(value: float, from_unit: str, to_unit: str) -> float:
    return _scale(value, from_unit, to_unit, WEIGHT, "weight")


def convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    for unit in (from_unit, to_unit):
        if unit not in TEMPERATURE:
            raise ValueError(f"unknown temperature unit '{unit}' (use one of: {', '.join(TEMPERATURE)})")
    celsius = {"C": value, "F": (value - 32) * 5 / 9, "K": value - 273.15}[from_unit]
    return {"C": celsius, "F": celsius * 9 / 5 + 32, "K": celsius + 273.15}[to_unit]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between any two units of the same kind, picking the kind from the units."""
    for factors, function in ((LENGTH, convert_length), (WEIGHT, convert_weight)):
        if from_unit in factors:
            return function(value, from_unit, to_unit)
    if from_unit in TEMPERATURE:
        return convert_temperature(value, from_unit, to_unit)
    known = [*LENGTH, *WEIGHT, *TEMPERATURE]
    raise ValueError(f"unknown unit '{from_unit}' (use one of: {', '.join(known)})")
