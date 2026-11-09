import unittest
from todo.storage import TodoStore


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = TodoStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_add_and_list(self):
        tid = self.store.add("buy milk")
        self.assertEqual(self.store.list(), [{"id": tid, "title": "buy milk", "done": False}])

    def test_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            self.store.add("   ")


if __name__ == "__main__":
    unittest.main()
