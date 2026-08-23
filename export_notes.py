#!/usr/bin/env python3
import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def clean_name(value: str, fallback: str) -> str:
    value = (value or "").strip() or fallback
    value = re.sub(r"[\\/:*?\"<>|\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:80].rstrip(". ") or fallback


def ms_to_iso(value: int | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_day(value: int | None) -> str:
    if not value:
        return "undated"
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def extract_json_text(display_content: str | None) -> str:
    if not display_content:
        return ""
    try:
        data = json.loads(display_content)
    except json.JSONDecodeError:
        return ""
    text = data.get("Text")
    return text if isinstance(text, str) else ""


def best_text(row: sqlite3.Row) -> str:
    json_text = extract_json_text(row["DisplayContent"])
    stripped = row["StrippedContent"] or ""
    content = json_text if len(json_text.strip()) >= len(stripped.strip()) else stripped
    return content.strip()


def local_wdoc_dir(local_state: Path, file_path: str | None, uuid: str) -> Path:
    if file_path:
        marker = "\\LocalState\\"
        if marker in file_path:
            rel = file_path.split(marker, 1)[1].replace("\\", "/")
            return local_state / rel
    return local_state / "wdoc" / uuid


def copy_file(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.name


def export_note(row: sqlite3.Row, extra: dict[str, sqlite3.Row], local_state: Path, out_dir: Path) -> dict:
    uuid = row["UUID"]
    title = row["Title"] or row["RecommendedTitle"] or row["StrippedTitle"] or ""
    text = best_text(row)
    day = ms_to_day(row["LastModifiedAt"] or row["CreatedAt"])
    folder = out_dir / clean_name(f"{uuid} {day} {title}", uuid)
    assets = folder / "assets"
    folder.mkdir(parents=True, exist_ok=True)

    media_files = []
    src_doc_dir = local_wdoc_dir(local_state, row["FilePath"], uuid)
    src_media = src_doc_dir / "media"
    if src_media.exists():
        for src in sorted(src_media.iterdir()):
            if src.is_file() and src.suffix.lower() in MEDIA_EXTS:
                name = copy_file(src, assets / clean_name(src.name, src.name))
                media_files.append(f"assets/{name}")

    thumb_files = []
    for col in ("ThumbnailPath", "ThumbnailPathCropped", "CoverThumbnailPathRect", "CoverThumbnailPathSquare"):
        raw = row[col]
        if not raw:
            continue
        src = local_state / raw.split("\\LocalState\\", 1)[-1].replace("\\", "/")
        if src.exists():
            name = copy_file(src, assets / clean_name(src.name, src.name))
            thumb_files.append(f"assets/{name}")

    extra_row = extra.get(uuid)
    meta = {
        "uuid": uuid,
        "title": title,
        "created_at": ms_to_iso(row["CreatedAt"]),
        "modified_at": ms_to_iso(row["LastModifiedAt"]),
        "deleted": row["DeletedStatus"],
        "locked": row["IsLocked"],
        "is_text_only": row["IsTextOnly"],
        "has_image": extra_row["hasImage"] if extra_row else 0,
        "has_stroke": extra_row["hasStroke"] if extra_row else 0,
        "has_pdf": extra_row["hasPdf"] if extra_row else 0,
        "media": media_files,
        "thumbnails": thumb_files,
    }

    lines = [
        "---",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "---",
        "",
        f"# {title or uuid}",
        "",
    ]
    if text:
        lines.extend([text, ""])
    for media in media_files:
        lines.append(f"![]({media})")
    if thumb_files and not media_files:
        lines.extend(["", "## Thumbnails"])
        lines.extend(f"![]({thumb})" for thumb in thumb_files[:1])

    (folder / "note.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {**meta, "path": str((folder / "note.md").relative_to(out_dir))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Samsung Notes to Markdown.")
    parser.add_argument("local_state", type=Path, help="Path to Samsung Notes LocalState directory")
    parser.add_argument("-o", "--out", type=Path, default=Path("exported_notes"), help="Output directory")
    parser.add_argument("--include-deleted", action="store_true", help="Export deleted notes too")
    args = parser.parse_args()

    db = args.local_state / "Storage.sqlite"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    extra = {
        row["UUID"]: row
        for row in con.execute("select UUID, hasImage, hasStroke, hasPdf from document_extra")
    }

    where = "" if args.include_deleted else "where DeletedStatus = 0"
    rows = con.execute(f"select * from NoteDB {where} order by LastModifiedAt desc, Id desc").fetchall()

    args.out.mkdir(parents=True, exist_ok=True)
    index = [export_note(row, extra, args.local_state, args.out) for row in rows]
    (args.out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(index)} notes to {args.out}")


if __name__ == "__main__":
    main()
