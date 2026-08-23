#!/usr/bin/env python3
import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Samsung Notes Storage.sqlite.")
    parser.add_argument("db", type=Path, help="Path to Storage.sqlite")
    args = parser.parse_args()

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    checks = [
        ("notes", "select count(*) n from NoteDB"),
        ("deleted", "select DeletedStatus, count(*) n from NoteDB group by DeletedStatus"),
        ("locked", "select IsLocked, count(*) n from NoteDB group by IsLocked"),
        ("text", """
            select
              sum(length(json_extract(DisplayContent,'$.Text')) > 0) json_text,
              sum(length(StrippedContent) > 0) stripped_text,
              sum(IsTextOnly = 1) text_only
            from NoteDB
        """),
        ("media_flags", """
            select hasImage, hasStroke, hasPdf, count(*) n
            from document_extra
            group by hasImage, hasStroke, hasPdf
            order by n desc
        """),
        ("modified_range", """
            select
              datetime(min(LastModifiedAt)/1000,'unixepoch') first_modified,
              datetime(max(LastModifiedAt)/1000,'unixepoch') last_modified
            from NoteDB
            where LastModifiedAt > 0
        """),
    ]

    for name, sql in checks:
        print(f"\n## {name}")
        rows = con.execute(sql).fetchall()
        if not rows:
            print("(empty)")
            continue
        print(" | ".join(rows[0].keys()))
        for row in rows:
            print(" | ".join("" if row[key] is None else str(row[key]) for key in row.keys()))


if __name__ == "__main__":
    main()
