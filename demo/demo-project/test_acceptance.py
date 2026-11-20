import os
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

# The app file name
APP = str(Path(__file__).resolve().parent / "app.py")

def page_text(app):
    parts = [str(element.value) for kind in ("markdown", "text", "caption", "success", "info", "warning", "error") for element in getattr(app, kind)]
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

    def test_full_flow(self):
        # 1. Start App and check initial state
        app = AppTest.from_file(APP, default_timeout=30).run()
        self.assertIn("Current Balance 0.00", page_text(app))

        # 2. Add an expense
        app.text_input[0].input("Salary")
        app.number_input[0].set_value(1000.0)
        next(b for b in app.button if b.label == "Add Expense").click().run()
        
        # 3. Subtract an expense
        app.text_input[0].input("Rent")
        app.number_input[0].set_value(400.0)
        next(b for b in app.button if b.label == "Subtract Amount").click().run()

        # 4. Verify results
        text = page_text(app)
        self.assertIn("Current Balance 600.00", text)
        self.assertIn("Salary", text)
        self.assertIn("Rent", text)
        self.assertFalse(app.exception, [e.message for e in app.exception])

if __name__ == "__main__":
    unittest.main()
