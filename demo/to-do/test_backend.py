import json
import tempfile
import unittest
from pathlib import Path

from backend import TodoStore


class TodoStoreTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "todos.json"

    def tearDown(self):
        self.folder.cleanup()

    def test_starts_empty_without_a_file(self):
        self.assertEqual(TodoStore(self.path).todos, [])

    def test_add_complete_delete_persist(self):
        store = TodoStore(self.path)
        milk = store.add("  Buy milk  ")
        bread = store.add("Buy bread")
        store.set_completed(milk["id"], True)
        store.delete(bread["id"])
        reloaded = TodoStore(self.path)
        self.assertEqual(reloaded.todos, [{"id": milk["id"], "task": "Buy milk", "completed": True}])

    def test_clear_completed(self):
        store = TodoStore(self.path)
        done = store.add("Done")
        store.add("Open")
        store.set_completed(done["id"], True)
        self.assertEqual(store.clear_completed(), 1)
        self.assertEqual([todo["task"] for todo in TodoStore(self.path).todos], ["Open"])

    def test_rejects_empty_and_too_long_tasks(self):
        store = TodoStore(self.path)
        with self.assertRaises(ValueError):
            store.add("   ")
        with self.assertRaises(ValueError):
            store.add("x" * 201)

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            TodoStore(self.path).delete("missing")

    def test_corrupt_file_is_ignored(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(TodoStore(self.path).todos, [])
        self.path.write_text(json.dumps({"todos": [{"task": "no id"}]}), encoding="utf-8")
        self.assertEqual(TodoStore(self.path).todos, [])


if __name__ == "__main__":
    unittest.main()
