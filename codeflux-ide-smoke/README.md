# Task Tracker CLI

A small, dependency-free command-line task tracker that stores tasks in `tasks.json`.

## Usage

Run these commands from the `codeflux-ide-smoke` directory.

Add a task:

```powershell
python tracker.py add "Buy groceries"
```

List tasks:

```powershell
python tracker.py list
```

## Testing

Run the built-in unittest suite:

```powershell
python -m unittest -v
```
