import sqlite3


class TodoStore:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS todos ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "title TEXT NOT NULL, "
            "done INTEGER NOT NULL DEFAULT 0)"
        )
        self.conn.commit()

    def add(self, title: str) -> int:
        if not title.strip():
            raise ValueError("title must not be empty")
        cur = self.conn.execute("INSERT INTO todos (title) VALUES (?)", (title.strip(),))
        self.conn.commit()
        return cur.lastrowid

    def list(self, include_done: bool = False):
        q = "SELECT id, title, done FROM todos"
        if not include_done:
            q += " WHERE done = 0"
        q += " ORDER BY id"
        return [
            {"id": r[0], "title": r[1], "done": bool(r[2])}
            for r in self.conn.execute(q)
        ]

    def mark_done(self, todo_id: int) -> None:
        cur = self.conn.execute("UPDATE todos SET done = 1 WHERE id = ?", (todo_id,))
        if cur.rowcount == 0:
            raise KeyError(todo_id)
        self.conn.commit()

    def close(self):
        self.conn.close()
