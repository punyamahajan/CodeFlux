import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent / "main.py")  # the file the README says to run


def page_text(app):
    parts = [str(element.value) for kind in ("header", "markdown", "text", "caption", "success", "info", "warning", "error") for element in getattr(app, kind)]
    parts += [f"{metric.label} {metric.value}" for metric in app.metric]
    parts += [frame.value.to_string() for frame in app.dataframe] + [table.value.to_string() for table in app.table]
    return "\n".join(parts)


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.previous = os.getcwd()
        self.folder = tempfile.TemporaryDirectory()
        os.chdir(self.folder.name)

    def tearDown(self):
        os.chdir(self.previous)
        self.folder.cleanup()

    def test_user_adds_an_item_and_sees_it(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input[0].set_value(12.5)
        app.text_input[0].input("Food")
        next(b for b in app.button if b.label == "Add").click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertIn("Food", page_text(app))

    def test_total_expenses_calculated_correctly(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input[0].set_value(100)
        app.text_input[0].input("Groceries")
        app.button[0].click().run()
        app.number_input[0].set_value(50)
        app.text_input[0].input("Utilities")
        app.button[0].click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertIn("Groceries: $100.00", page_text(app))
        self.assertIn("Utilities: $50.00", page_text(app))

    def test_data_is_still_there_after_a_restart(self):
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input[0].set_value(12.5)
        app.text_input[0].input("Food")
        app.button[0].click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        
        # Restart the app
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertIn("Food", page_text(app))
        self.assertIn("Category Totals", page_text(app))
