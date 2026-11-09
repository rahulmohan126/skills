# todo-cli
A tiny SQLite-backed todo CLI.

    python3 -m todo --db todos.db add "buy milk"
    python3 -m todo --db todos.db list
    python3 -m todo --db todos.db done 1

Run tests: `python3 -m unittest discover -s tests`
