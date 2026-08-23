from app.worker import recover


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def select(self, *_args): return self
    def in_(self, *_args): return self
    def order(self, *_args): return self
    def eq(self, *_args): return self
    def execute(self):
        return type("Response", (), {"data": self.rows})()
    def update(self, payload):
        self.updates.append(payload)
        self.rows = []
        return self


class FakeClient:
    def __init__(self, tasks):
        self.queries = {
            "processing_tasks": FakeQuery(tasks),
            "materials": FakeQuery([]),
        }

    def table(self, name):
        return self.queries[name]


def test_recovery_requeues_running_and_queued_tasks(monkeypatch):
    tasks = [
        {"id": "running-task", "user_id": "user", "material_id": "one", "status": "running", "attempts": 1},
        {"id": "queued-task", "user_id": "user", "material_id": "two", "status": "queued", "attempts": 0},
    ]
    client = FakeClient(tasks)
    dispatched = []
    monkeypatch.setattr(recover, "get_supabase_client", lambda: client)
    monkeypatch.setattr(recover.process_material, "delay", dispatched.append)

    assert recover.recover_unfinished_tasks() == 2
    assert dispatched == ["running-task", "queued-task"]
    assert client.queries["processing_tasks"].updates[0]["status"] == "queued"
    assert client.queries["processing_tasks"].updates[0]["attempts"] == 0
