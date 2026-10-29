# Unit converter

A dependency-free command-line unit converter.

| Kind | Units |
|---|---|
| Length | `m`, `km`, `mi` |
| Weight | `g`, `kg`, `lb` |
| Temperature | `C`, `F`, `K` |

## Usage

```powershell
python cli.py 10 km mi     # 10 km = 6.214 mi
python cli.py 2.5 kg lb    # 2.5 kg = 5.512 lb
python cli.py 100 C F      # 100 C = 212 F
```

Unknown units or mixing kinds (for example `km` to `kg`) print an error and exit with code 1.

## Tests

```powershell
python -m unittest -v
```
