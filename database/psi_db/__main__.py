"""CLI:  python -m psi_db <command>   (see DATABASE.md section 10)"""

import argparse
import json


def main():
    p = argparse.ArgumentParser(
        prog="psi_db", description="PSI combustion experiments database"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser(
        "reports", help="PDF -> text for every experiment in raw dataset"
    )
    r.add_argument(
        "--force", action="store_true", help="re-extract even if the .txt exists"
    )
    sub.add_parser("catalog", help="build studies.csv + studies.json")
    sub.add_parser("build", help="build psi.db")
    sub.add_parser("all", help="reports + catalog + build")
    sub.add_parser("status", help="which experiments have metadata / report")

    s = sub.add_parser("search", help="quick search test in the terminal")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)

    v = sub.add_parser("serve", help="start the API")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--reload", action="store_true")

    a = p.parse_args()

    if a.cmd == "reports":
        from .reports import extract_all

        extract_all(a.force)
    elif a.cmd == "catalog":
        from .catalog import build_catalog

        build_catalog()
    elif a.cmd == "build":
        from .database import build_db

        build_db()
    elif a.cmd == "all":
        from .catalog import build_catalog
        from .database import build_db
        from .reports import extract_all

        extract_all()
        build_catalog()
        build_db()
    elif a.cmd == "status":
        from .status import print_coverage

        print_coverage()
    elif a.cmd == "search":
        import sqlite3
        from . import config
        from .search import SearchSpec, search

        con = sqlite3.connect(config.DB_PATH)
        print(
            json.dumps(
                search(con, SearchSpec(text=a.query, limit=a.limit)),
                indent=2,
                ensure_ascii=False,
            )
        )
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("psi_db.api:app", host=a.host, port=a.port, reload=a.reload)


if __name__ == "__main__":
    main()
