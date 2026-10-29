# Kept so `streamlit run main.py` still works; the app lives in todo_list.py.
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("todo_list.py")), run_name="__main__")
