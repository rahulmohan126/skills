import argparse
import sys

from .storage import TodoStore


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="todo")
    p.add_argument("--db", default="todos.db")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("title")
    l = sub.add_parser("list")
    l.add_argument("--all", action="store_true")
    d = sub.add_parser("done")
    d.add_argument("id", type=int)
    args = p.parse_args(argv)

    store = TodoStore(args.db)
    try:
        if args.cmd == "add":
            try:
                tid = store.add(args.title)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            print(f"added {tid}")
        elif args.cmd == "list":
            for t in store.list(include_done=args.all):
                mark = "x" if t["done"] else " "
                print(f"[{mark}] {t['id']}: {t['title']}")
        elif args.cmd == "done":
            try:
                store.mark_done(args.id)
            except KeyError:
                print(f"error: no todo {args.id}", file=sys.stderr)
                return 1
            print(f"done {args.id}")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
