"""Validate release JARs and generate one update manifest per Minecraft version."""

import argparse
import hashlib
import json
import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASES = ROOT / "release" / "mc"
RAW_BASE = "https://raw.githubusercontent.com/Gaksvord/GaksPack/main/release/mc"
NAME = re.compile(r"GaksPack-(\d+)\.(\d+)\.(\d+)\+mc([0-9.]+)\.jar$")
MAX_SIZE = 95 * 1024 * 1024


def validate(path, minecraft):
    match = NAME.fullmatch(path.name)
    if not match or match.group(4) != minecraft:
        raise ValueError(f"Invalid release filename: {path}")
    size = path.stat().st_size
    if not 0 < size <= MAX_SIZE:
        raise ValueError(f"Invalid release size: {path}")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"Corrupt release JAR: {path}")
        metadata = json.loads(archive.read("fabric.mod.json"))
    version = path.name.removeprefix("GaksPack-").removesuffix(".jar")
    if metadata.get("id") != "gakspack" or metadata.get("version") != version:
        raise ValueError(f"Mod id or version mismatch: {path}")
    if metadata.get("depends", {}).get("minecraft") != minecraft:
        raise ValueError(f"Minecraft version mismatch: {path}")
    if metadata.get("authors") != ["Gaksvord"]:
        raise ValueError(f"Author mismatch: {path}")
    if metadata.get("contact", {}).get("homepage") != "https://t.me/GurikTeam":
        raise ValueError(f"Contact mismatch: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return tuple(map(int, match.group(1, 2, 3))), version, size, digest


def sync(minecraft, write):
    folder = RELEASES / minecraft
    if not folder.is_dir() or not re.fullmatch(r"[0-9.]+", minecraft):
        raise ValueError(f"Unknown Minecraft version: {minecraft}")
    jars = list(folder.glob("GaksPack-*.jar"))
    if not jars:
        return False
    _semver, version, size, digest, name = max(
        (*validate(path, minecraft), path.name) for path in jars
    )
    manifest = {
        "version": version,
        "minecraft": minecraft,
        "url": f"{RAW_BASE}/{minecraft}/{name}",
        "sha256": digest,
        "size": size,
    }
    target = folder / "version.json"
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    changed = not target.exists() or target.read_text(encoding="utf-8") != content
    if changed and write:
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
    print(f"{minecraft}: {version} changed={changed}")
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("versions", nargs="*", help="Minecraft versions; all release folders by default")
    parser.add_argument("--write", action="store_true", help="write version.json files")
    arguments = parser.parse_args()
    versions = arguments.versions or [item.name for item in sorted(RELEASES.iterdir()) if item.is_dir()]
    changed = False
    for item in versions:
        changed = sync(item, arguments.write) or changed
    raise SystemExit(0 if arguments.write or not changed else 1)
