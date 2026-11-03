"""
GaksPack - publish or remove styles that every GaksPack user sees.

Only works for the owner of the GitHub repository: the files are pushed with git,
and git only lets the account with write access push. Nothing secret is stored here.

    python stylesgaksvord.py publish <pack.zip> [preview.png]
    python stylesgaksvord.py publish-auto <pack.zip> <category> <name> [preview.png]
    python stylesgaksvord.py remove
    python stylesgaksvord.py remove-auto <style id>

publish-auto asks nothing and replaces a style with the same name; the upload
page in the mod uses it.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
REPO_DIR = (os.environ.get("GAKSPACK_REPO_DIR")
            or (_PARENT if os.path.isdir(os.path.join(_PARENT, ".git")) else None)
            or os.path.join(os.path.expanduser("~"), "GaksPack"))
MAX_PACK = 95 * 1024 * 1024
CATEGORIES = ["crystal", "anchor", "armor", "fire", "sky", "obsidian", "sword", "pickaxe", "glowstone", "gap", "pearl", "hotbar", "axe", "totem", "stone", "deepslate", "snow", "inventory"]


def say(text=""):
    print(text, flush=True)


def ask(question, default=""):
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def git(*args, check=True):
    result = subprocess.run(["git", "-C", REPO_DIR, *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{result.stderr.strip() or result.stdout.strip()}")
    return result


def load_index():
    path = os.path.join(REPO_DIR, "index.json")
    if not os.path.exists(path):
        return {"version": 1, "styles": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_index(index):
    index["styles"].sort(key=lambda s: s.get("added", ""), reverse=True)
    with open(os.path.join(REPO_DIR, "index.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
        f.write("\n")


def ensure_repo():
    if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        raise SystemExit(f"No Git clone is configured at {REPO_DIR}.\n"
                         f"Clone it once:  git clone https://github.com/Gaksvord/GaksPack.git \"{REPO_DIR}\"")
    say("Updating local copy...")
    git("fetch", "origin", "main", "--quiet")
    git("merge", "--ff-only", "origin/main")
    for folder in ("packs", "previews"):
        os.makedirs(os.path.join(REPO_DIR, folder), exist_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def guess_category(names):
    joined = "\n".join(names).lower()
    if "optifine/sky/" in joined:
        return "sky"
    if "end_crystal" in joined:
        return "crystal"
    if "respawn_anchor" in joined:
        return "anchor"
    if "equipment/humanoid" in joined or "_chestplate" in joined or "diamond_layer" in joined:
        return "armor"
    if "block/fire_0" in joined or "block/fire_1" in joined:
        return "fire"
    if "/obsidian.png" in joined:
        return "obsidian"
    if "_sword.png" in joined:
        return "sword"
    if "_pickaxe.png" in joined:
        return "pickaxe"
    if "/glowstone.png" in joined:
        return "glowstone"
    return ""


def slug(text):
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")[:40]


def make_preview(source, target):
    try:
        from PIL import Image
        img = Image.open(source).convert("RGBA")
        side = min(img.size)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((256, 256), Image.LANCZOS)
        img.save(target, "PNG", optimize=True)
    except ImportError:
        if os.path.getsize(source) > 2 * 1024 * 1024:
            raise SystemExit("Preview is bigger than 2 MB and Pillow is not installed to shrink it.")
        if os.path.abspath(source) != os.path.abspath(target):
            shutil.copyfile(source, target)


def publish(zip_path, preview_path=None, auto=None):
    """auto = (category, name) skips every question."""
    if not zip_path.lower().endswith(".zip") or not os.path.isfile(zip_path):
        raise SystemExit("Drop a .zip resource pack onto the publish file.")
    size = os.path.getsize(zip_path)
    if size > MAX_PACK:
        raise SystemExit(f"Pack is {size / 1024 / 1024:.1f} MB - the limit is 95 MB.")
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            bad = z.testzip()
            if bad:
                raise SystemExit(f"Corrupt ZIP entry: {bad}")
    except zipfile.BadZipFile:
        raise SystemExit("That file is not a valid zip.")
    if not any(n.replace("\\", "/").startswith("assets/") for n in names):
        raise SystemExit("The zip has no assets/ folder - is it really a resource pack?")

    ensure_repo()
    index = load_index()

    if auto:
        category, name = auto[0], auto[1].strip()[:40]
        # the built-in collections plus the ones index.json adds ("categories")
        online = [c.get("id") for key in ("categories", "adminCategories") for c in index.get(key, []) if isinstance(c, dict)]
        if category not in CATEGORIES and category not in online:
            raise SystemExit(f"Unknown category: {category}")
    else:
        say()
        say("Categories: 1 crystal   2 anchor   3 armor   4 fire   5 sky")
        guess = guess_category(names)
        default = str(CATEGORIES.index(guess) + 1) if guess else ""
        choice = ask("Category", default)
        if choice not in {"1", "2", "3", "4", "5"}:
            raise SystemExit("Category must be 1-5.")
        category = CATEGORIES[int(choice) - 1]
        base_name = os.path.splitext(os.path.basename(zip_path))[0]
        name = ask("Name shown in the menu", base_name.replace("_", " ").strip()[:40])[:40]
    if category == "sky" and not any("optifine/sky/" in n for n in names):
        raise SystemExit("Sky styles need assets/minecraft/optifine/sky/ in the zip.")

    style_id = f"{category}_{slug(name)}"
    if style_id == f"{category}_":
        raise SystemExit("The name needs at least one letter or digit.")

    existing = next((s for s in index["styles"] if s["id"] == style_id), None)
    if existing and not auto and ask(f"'{name}' already exists. Replace it? (y/n)", "n").lower() != "y":
        raise SystemExit("Nothing changed.")

    if not preview_path and not auto:
        preview_path = ask("Preview image (drag a .png here, or Enter to skip)", "").strip('"')
    pack_target = os.path.join(REPO_DIR, "packs", style_id + ".zip")
    if os.path.abspath(zip_path) != os.path.abspath(pack_target):
        shutil.copyfile(zip_path, pack_target)
    entry = {
        "id": style_id,
        "category": category,
        "name": name,
        "sha256": sha256(pack_target),
        "size": os.path.getsize(pack_target),
        "added": existing["added"] if existing else datetime.date.today().isoformat(),
    }
    if preview_path:
        if not os.path.isfile(preview_path):
            raise SystemExit(f"Preview not found: {preview_path}")
        make_preview(preview_path, os.path.join(REPO_DIR, "previews", style_id + ".png"))
        entry["preview"] = f"previews/{style_id}.png"
    elif existing and existing.get("preview"):
        entry["preview"] = existing["preview"]

    index["styles"] = [s for s in index["styles"] if s["id"] != style_id] + [entry]
    save_index(index)

    say("Uploading...")
    git("add", "--", "index.json", f"packs/{style_id}.zip")
    if entry.get("preview"):
        git("add", "--", entry["preview"])
    git("commit", "--quiet", "-m", f"{'Update' if existing else 'Add'} {category} style: {name}")
    git("push", "--quiet")
    say()
    say(f"Done. '{name}' ({category}) is live. Players see it the next time they open the menu")
    say("(GitHub can take up to 5 minutes to hand out the new list).")


def remove():
    ensure_repo()
    index = load_index()
    styles = index["styles"]
    if not styles:
        raise SystemExit("There are no Gaksvord styles yet.")
    say()
    for i, s in enumerate(styles, 1):
        say(f"{i:>3}  {s['category']:<8} {s['name']}  (added {s.get('added', '?')})")
    choice = ask("Number to remove (Enter to cancel)", "")
    if not choice:
        raise SystemExit("Nothing changed.")
    if not choice.isdigit() or not 1 <= int(choice) <= len(styles):
        raise SystemExit("Not a number from the list.")
    style = styles[int(choice) - 1]
    if ask(f"Remove '{style['name']}' for everyone? (y/n)", "n").lower() != "y":
        raise SystemExit("Nothing changed.")
    for rel in (f"packs/{style['id']}.zip", style.get("preview")):
        if rel and os.path.exists(os.path.join(REPO_DIR, rel)):
            os.remove(os.path.join(REPO_DIR, rel))
    index["styles"] = [s for s in styles if s["id"] != style["id"]]
    save_index(index)
    git("add", "-A", "--", "index.json", f"packs/{style['id']}.zip")
    if style.get("preview"):
        git("add", "-A", "--", style["preview"])
    git("commit", "--quiet", "-m", f"Remove {style['category']} style: {style['name']}")
    git("push", "--quiet")
    say(f"Removed '{style['name']}'.")


def remove_auto(style_id):
    """Removes one style by id without asking - used by the mod's upload page."""
    ensure_repo()
    index = load_index()
    style = next((s for s in index["styles"] if s["id"] == style_id), None)
    if style is None:
        raise SystemExit(f"No published style with id {style_id}")
    for rel in (f"packs/{style['id']}.zip", style.get("preview")):
        if rel and os.path.exists(os.path.join(REPO_DIR, rel)):
            os.remove(os.path.join(REPO_DIR, rel))
    index["styles"] = [s for s in index["styles"] if s["id"] != style_id]
    save_index(index)
    git("add", "-A", "--", "index.json", f"packs/{style['id']}.zip")
    if style.get("preview"):
        git("add", "-A", "--", style["preview"])
    git("commit", "--quiet", "-m", f"Remove {style['category']} style: {style['name']}")
    git("push", "--quiet")
    say(f"Removed '{style['name']}'.")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"publish", "publish-auto", "remove", "remove-auto"}:
        raise SystemExit(__doc__)
    if sys.argv[1] == "remove":
        remove()
        return
    if sys.argv[1] == "remove-auto":
        if len(sys.argv) < 3:
            raise SystemExit(__doc__)
        remove_auto(sys.argv[2])
        return
    if sys.argv[1] == "publish-auto":
        if len(sys.argv) < 5:
            raise SystemExit(__doc__)
        publish(sys.argv[2], sys.argv[5] if len(sys.argv) > 5 else None, auto=(sys.argv[3], sys.argv[4]))
        return
    files = [a for a in sys.argv[2:]]
    zips = [f for f in files if f.lower().endswith(".zip")]
    pngs = [f for f in files if f.lower().endswith(".png")]
    if len(zips) != 1:
        raise SystemExit("Drop exactly one .zip (and optionally one .png preview) onto the publish file.")
    publish(zips[0], pngs[0] if pngs else None)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nCancelled.")
