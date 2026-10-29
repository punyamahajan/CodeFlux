"""Command-line unit converter: python cli.py 10 km mi"""
import sys

from converter import convert


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Usage: python cli.py <value> <from_unit> <to_unit>   e.g. python cli.py 10 km mi")
        return 2
    try:
        value = float(argv[0])
        result = convert(value, argv[1], argv[2])
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"{value:g} {argv[1]} = {result:.4g} {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
