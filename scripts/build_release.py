"""Build a source release containing code/assets, never local settings or caches."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {'actions', 'core', 'memory', 'config', 'dashboard', 'plugins', 'tests', 'scripts'}
EXTENSIONS = {'.py', '.txt', '.md', '.obj', '.jpeg', '.jpg', '.png', '.ico', '.svg', '.html', '.css', '.js'}


def release_files(root=ROOT):
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if not path.is_file() or path.is_symlink():
            continue
        if any(part.startswith('.') or part in ('__pycache__', 'venv', 'env', 'dist', 'build', 'screenshots', 'logs', 'downloads') for part in relative.parts):
            continue
        if len(relative.parts) > 1 and relative.parts[0] not in DIRECTORIES:
            continue
        if relative.parts[0] == 'config' and str(relative).replace('\\', '/') not in ('config/__init__.py', 'config/api_keys.json.example', 'config/jarvis.ico'):
            continue
        if path.name == 'api_keys.json.example' or str(relative).replace('\\', '/') == 'memory/workspace_presets.json' or path.suffix.lower() in EXTENSIONS:
            yield path, relative


def build(output, root=ROOT):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = list(release_files(root))
    if not entries:
        raise ValueError('No release files were found.')
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for path, relative in entries:
            archive.write(path, 'Ultron/' + relative.as_posix())
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{checksum}  {output.name}\n', encoding='utf-8')
    return len(entries), checksum


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'dist/Ultron-source.zip')
    arguments = parser.parse_args()
    count, digest = build(arguments.output)
    print(f'Built {arguments.output} ({count} files)')
    print('SHA-256:', digest)
