import os
import tempfile
import unittest

from app.models import Task
from app.storage import TaskStore


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = TaskStore(self.tmp.name)

    def tearDown(self):
        os.remove(self.tmp.name)

    def test_crud_and_complete(self):
        created = self.store.add_task(
            Task(title="Buy milk", due_date="2026-07-07", due_time="09:00")
        )
        self.assertIsNotNone(created.id)

        tasks = self.store.list_tasks(day="2026-07-07")
        self.assertEqual(len(tasks), 1)

        updated = self.store.update_task(
            Task(
                id=created.id,
                title="Buy milk and bread",
                due_date="2026-07-07",
                due_time="09:00",
            )
        )
        self.assertEqual(updated.title, "Buy milk and bread")

        completed = self.store.complete_task(created.id)
        self.assertTrue(completed.completed)

        self.store.delete_task(created.id)
        self.assertIsNone(self.store.get_task(created.id))


if __name__ == "__main__":
    unittest.main()
