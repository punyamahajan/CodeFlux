import os
import unittest

from tracker import add_task, list_tasks, load_tasks, save_tasks


class TestTaskTracker(unittest.TestCase):
    def setUp(self):
        self.test_file = "tasks.json"
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_add_task(self):
        add_task("Test task")
        tasks = load_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["title"], "Test task")

    def test_save_and_load_tasks(self):
        expected = [{"title": "Persisted task", "done": True}]
        save_tasks(expected)
        self.assertEqual(load_tasks(), expected)

    def test_list_empty_tasks(self):
        self.assertIsNone(list_tasks())


if __name__ == "__main__":
    unittest.main()
