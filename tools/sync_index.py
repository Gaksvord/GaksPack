"""Validate packs and refresh index.json after files are added to the repository."""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import struct
import sys
import zipfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.json"
MAX_PACK = 95 * 1024 * 1024
MAX_PREVIEW = 2 * 1024 * 1024
ID = re.compile(r"^[a-z][a-z0-9]{1,15}_[a-z0-9_]{1,40}$")
PNG = b"\x89PNG\r\n\x1a\n"
DEFAULT_CATEGORIES = {"crystal", "anchor", "armor", "fire", "sky", "obsidian", "sword", "pickaxe", "glowstone", "gap", "pearl", "hotbar", "axe", "totem", "stone", "deepslate", "snow", "inventory", "shield", "elytra", "trident", "mace", "windcharge", "spear", "cobweb", "tntcart", "rails", "xpbottle"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_pack(path):
    size = path.stat().st_size
    if size == 0 or size > MAX_PACK:
        raise ValueError(f"{path.name}: ZIP must be between 1 byte and 95 MiB")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not any(name.replace("\\", "/").startswith("assets/") for name in names):
            raise ValueError(f"{path.name}: missing assets/ folder")
        if archive.testzip() is not None:
            raise ValueError(f"{path.name}: corrupt ZIP member")
        if sum(item.file_size for item in archive.infolist()) > 400 * 1024 * 1024:
            raise ValueError(f"{path.name}: unpacked size exceeds 400 MiB")
    return size, digest(path)



def verify_preview(path):
    data = path.read_bytes()
    if len(data) > MAX_PREVIEW or not data.startswith(PNG):
        raise ValueError(f"Invalid PNG preview: {path.name}")
    offset = len(PNG)
    ended = False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + 12 + length
        if end > len(data):
            raise ValueError(f"Truncated PNG preview: {path.name}")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        expected = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) != expected:
            raise ValueError(f"Damaged PNG preview: {path.name}")
        offset = end
        if kind == b"IEND":
            ended = True
            break
    if not ended:
        raise ValueError(f"Incomplete PNG preview: {path.name}")


def main(write):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    old = {entry["id"]: entry for entry in index["styles"]}
    categories = DEFAULT_CATEGORIES | {entry["category"] for entry in old.values()}
    categories |= {item["id"] for key in ("categories", "adminCategories") for item in index.get(key, []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    results = {}
    for pack in sorted((ROOT / "packs").glob("*.zip")):
        style_id = pack.stem
        if not ID.fullmatch(style_id):
            raise ValueError(f"Invalid pack filename: {pack.name}")
        if style_id in old:
            entry = old[style_id].copy()
        else:
            category = next((name for name in sorted(categories, key=len, reverse=True) if style_id.startswith(name + "_")), None)
            if category is None:
                raise ValueError(f"Unknown category in filename: {pack.name}")
            entry = {"id": style_id, "category": category, "name": style_id[len(category) + 1:].replace("_", " ").title(), "added": dt.date.today().isoformat()}
        size, sha = verify_pack(pack)
        entry["size"] = size
        entry["sha256"] = sha
        preview = ROOT / "previews" / (style_id + ".png")
        if preview.is_file():
            verify_preview(preview)
            entry["preview"] = "previews/" + preview.name
        else:
            entry.pop("preview", None)
        results[style_id] = entry
    updated = [results[entry["id"]] for entry in index["styles"] if entry["id"] in results]
    updated.extend(results[key] for key in sorted(results.keys() - old.keys()))
    changed = updated != index["styles"]
    added = len(results.keys() - old.keys())
    removed = len(old.keys() - results.keys())
    index["styles"] = updated
    if changed and write:
        temp = INDEX.with_suffix(".json.tmp")
        temp.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(INDEX)
    print(f"styles={len(updated)} added={added} removed={removed} changed={changed}")
    return 0 if write or not changed else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="save updated index.json")
    args = parser.parse_args()
    try:
        sys.exit(main(args.write))
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError) as error:
        print(f"catalog error: {error}", file=sys.stderr)
        sys.exit(2)
