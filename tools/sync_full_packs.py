"""Refresh the owner-managed full pack catalog before committing to GitHub."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

root = Path(__file__).resolve().parents[1] / 'full-packs'
index = root / 'index.json'
old = {p['id']: p for p in json.loads(index.read_text(encoding='utf-8')).get('packs', [])}
packs = []
for path in sorted(root.glob('*.zip')):
    if not re.fullmatch(r'[a-z0-9_]{1,48}', path.stem):
        raise ValueError(f'Invalid filename: {path.name}. Use lowercase Latin letters, numbers and underscores.')
    if path.stat().st_size > 95 * 1024 * 1024:
        raise ValueError(f'Pack is larger than 95 MiB: {path.name}')
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None or 'pack.mcmeta' not in archive.namelist():
            raise ValueError(f'Invalid resource pack: {path.name}')
        if sum(entry.file_size for entry in archive.infolist()) > 400 * 1024 * 1024:
            raise ValueError(f'Unpacked pack is larger than 400 MiB: {path.name}')
        metadata = json.loads(archive.read('pack.mcmeta').decode('utf-8-sig'))
        if not isinstance(metadata.get('pack'), dict):
            raise ValueError(f'Invalid pack.mcmeta: {path.name}')
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    packs.append({'id': path.stem, 'name': old.get(path.stem, {}).get('name', path.stem.replace('_', ' ').title()),
                  'size': path.stat().st_size, 'sha256': sha.hexdigest()})
index.write_text(json.dumps({'packs': packs}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Full packs: {len(packs)}')
