import os
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

# The app.py is the entry point defined in the project plan/README
APP = str(Path(__file__).resolve().parent / "app.py")

def page_text(app):
    parts = [str(element.value) for kind in ("markdown", "text", "caption", "success", "info", "warning", "error") for element in getattr(app, kind)]
    parts += [f"{metric.label} {metric.value}" for metric in app.metric]
    # Represent DataFrames and Tables as strings to verify content
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
        # 1. Start App and add an expense
        app = AppTest.from_file(APP, default_timeout=30).run()
        app.number_input[0].set_value(50.0).run()
        app.text_input[0].input("Food").run()
        app.button[0].click().run()
        
        # Verify success message and inclusion in UI
        self.assertFalse(app.exception, [e.message for e in app.exception])
        text = page_text(app)
        self.assertIn("Food", text)
        self.assertIn("50.0", text)
        
        # 2. Verify data persists by restarting the app
        app2 = AppTest.from_file(APP, default_timeout=30).run()
        text2 = page_text(app2)
        self.assertIn("Food", text2)
        self.assertIn("50.0", text2)
        
        # 3. Add second expense to same category to check totals
        app2.number_input[0].set_value(25.0).run()
        app2.text_input[0].input("Food").run()
        app2.button[0].click().run()
        
        text3 = page_text(app2)
        # Check that total for Food shows 75.0 (50 + 25)
        self.assertIn("75.0", text3)

if __name__ == "__main__":
    unittest.main()
