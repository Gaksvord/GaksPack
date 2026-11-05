"""Validate packs and refresh index.json after files are added to the repository."""

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import struct
import sys
import os
import zipfile
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.json"
MAX_PACK = 95 * 1024 * 1024
MAX_PREVIEW = 2 * 1024 * 1024
PACK_DESCRIPTION = "GaksPack textures - by gaksvord"
ID = re.compile(r"^[a-z][a-z0-9_]{1,31}_[a-z0-9_]{1,40}$")
MOB_PACK = re.compile(r"^mob_([a-z0-9_]{2,25})__([a-z0-9_]{1,40})$")
EXCLUDED_MOBS = {"silverfish", "phantom"}
ENTITY_PREFIX = "assets/minecraft/textures/entity/"
PNG = b"\x89PNG\r\n\x1a\n"
DEFAULT_CATEGORIES = {"crystal", "anchor", "armor", "fire", "sky", "obsidian", "sword", "pickaxe", "glowstone", "gap", "pearl", "hotbar", "axe", "totem", "stone", "deepslate", "snow", "inventory", "shield", "elytra", "trident", "mace", "windcharge", "spear", "cobweb", "tntcart", "rails", "xpbottle"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pack_description(path):
    with zipfile.ZipFile(path) as archive:
        if "pack.mcmeta" not in archive.namelist():
            return None
        try:
            return json.loads(archive.read("pack.mcmeta"))["pack"]["description"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            return None


def normalize_pack_meta(path):
    """Replace only the root pack description, preserving the other ZIP entries."""
    temporary = path.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
            target.comment = source.comment
            entries = source.infolist()
            original = next((item for item in entries if item.filename == "pack.mcmeta"), None)
            try:
                metadata = json.loads(source.read(original).decode("utf-8-sig")) if original else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            pack = metadata.get("pack")
            if not isinstance(pack, dict):
                pack = {"pack_format": 75, "min_format": 65, "max_format": 9999}
            pack["description"] = PACK_DESCRIPTION
            metadata["pack"] = pack
            replacement = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            for item in entries:
                target.writestr(item, replacement if item.filename == "pack.mcmeta" else source.read(item))
            if original is None:
                target.writestr("pack.mcmeta", replacement, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_pack(path):
    size = path.stat().st_size
    if size == 0 or size > MAX_PACK:
        raise ValueError(f"{path.name}: ZIP must be between 1 byte and 95 MiB")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if not any(name.replace("\\", "/").startswith("assets/") for name in names):
            raise ValueError(f"{path.name}: missing assets/ folder")
        if MOB_PACK.fullmatch(path.stem):
            mob_files(archive, path.name)
        if archive.testzip() is not None:
            raise ValueError(f"{path.name}: corrupt ZIP member")
        if sum(item.file_size for item in archive.infolist()) > 400 * 1024 * 1024:
            raise ValueError(f"{path.name}: unpacked size exceeds 400 MiB")
    return size, digest(path)


def mob_files(archive, name):
    files = set()
    for member in archive.namelist():
        path = member.replace("\\", "/").lower()
        if not path.startswith(ENTITY_PREFIX) or not path.endswith(".png") or ".." in path:
            continue
        relative = path[len(ENTITY_PREFIX):]
        if any(re.match(rf"^{mob}(?:_|$)", part) for mob in EXCLUDED_MOBS for part in relative.removesuffix(".png").split("/")):
            raise ValueError(f"{name}: silverfish and phantom textures are not allowed")
        files.add(relative)
    if not files:
        raise ValueError(f"{name}: no mob textures under {ENTITY_PREFIX}")
    return files


def mob_rules(files):
    rules = []
    group = []
    for path in sorted(files):
        escaped = re.escape(path)
        candidate = group + [escaped]
        pattern = f"^{ENTITY_PREFIX}({'|'.join(candidate)})$"
        if len(f"^{ENTITY_PREFIX}({escaped})$") > 300:
            raise ValueError(f"Mob texture path is too long: {path}")
        if len(pattern) > 300 and group:
            rules.append({"match": f"^{ENTITY_PREFIX}({'|'.join(group)})$", "to": ENTITY_PREFIX + "$1"})
            group = [escaped]
        else:
            group = candidate
    if group:
        rules.append({"match": f"^{ENTITY_PREFIX}({'|'.join(group)})$", "to": ENTITY_PREFIX + "$1"})
    if len(rules) > 32:
        raise ValueError("Too many distinct mob texture paths (maximum 32 rule groups)")
    return rules


def add_mob_categories(index):
    categories = index.setdefault("categories", [])
    known = {entry["id"]: entry for entry in categories}
    taken = {entry["slot"] for entry in categories if isinstance(entry.get("slot"), int)}
    added = 0
    mob_paths = {}
    for pack in sorted((ROOT / "packs").glob("mob_*__*.zip")):
        match = MOB_PACK.fullmatch(pack.stem)
        if not match:
            raise ValueError(f"Invalid mob pack name: {pack.name}; use mob_zombie__style.zip")
        mob = match.group(1)
        if mob in EXCLUDED_MOBS:
            raise ValueError(f"{mob} is not available in GaksPack")
        category = "mob_" + mob
        with zipfile.ZipFile(pack) as archive:
            mob_paths.setdefault(category, set()).update(mob_files(archive, pack.name))
        if category in known:
            continue
        slot = next((number for number in range(11, 139) if number not in taken), None)
        if slot is None:
            raise ValueError("The mob list is full (128 types)")
        definition = {
            "id": category, "slot": slot, "name": mob.replace("_", " ").title(),
            "icon": f"minecraft:{mob}_spawn_egg",
            "autoMob": True
        }
        categories.append(definition)
        known[category] = definition
        taken.add(slot)
        added += 1
    for category, paths in mob_paths.items():
        definition = known[category]
        if definition.get("autoMob"):
            definition["files"] = mob_rules(paths)
            definition["preview"] = {"type": "item", "texture": ENTITY_PREFIX + sorted(paths)[0]}
    return added



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
    categories_before = json.dumps(index.get("categories", []), sort_keys=True)
    added_mobs = add_mob_categories(index)
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
        current_sha = digest(pack)
        description = pack_description(pack)
        if write and (style_id not in old or current_sha != old[style_id].get("sha256") or (isinstance(description, str) and "bauloo" in description.lower())):
            normalize_pack_meta(pack)
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
    changed = updated != index["styles"] or added_mobs > 0 or categories_before != json.dumps(index.get("categories", []), sort_keys=True)
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
