"""Package a clean CPython embeddable distribution with preinstalled dependencies.

Run with the same Python major/minor and architecture as the embedded interpreter.
Install requirements and pip into its Lib/site-packages before calling this script.
Never point --python-dir at a personal Python installation or virtual environment.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import zipfile


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-dir', required=True, type=Path)
    parser.add_argument('--ffmpeg-dir', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'vendor' / 'windows-x64'
    output.mkdir(parents=True, exist_ok=True)
    python = args.python_dir.resolve()
    ffmpeg = args.ffmpeg_dir.resolve()
    pth_files = list(python.glob('python*._pth'))
    if len(pth_files) != 1 or not (python / 'LICENSE.txt').is_file():
        raise SystemExit('Expected an official Windows embeddable Python distribution.')
    pth = pth_files[0]
    # Installed location: <project>/python.
    # Use Windows separators: embedded getpath handles forward-slash '..' paths
    # differently. No 'import site': keep personal/user packages out of this bundle.
    pth.write_text(f'{pth.stem}.zip\n.\nLib\\site-packages\n..\n', encoding='utf-8')
    packages = []

    def archive(name, entries):
        dest = output / name
        with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for source, target in entries:
                z.write(source, target)
        if dest.stat().st_size >= 100 * 1024 * 1024:
            raise SystemExit(f'{dest.name} exceeds GitHub file size limit.')
        packages.append({'file': name, 'sha256': sha256(dest), 'bytes': dest.stat().st_size})
        print(f'{name}: {dest.stat().st_size / 1024 / 1024:.1f} MiB', flush=True)

    entries = []
    for path in sorted(python.rglob('*')):
        relative = path.relative_to(python)
        if not path.is_file() or '__pycache__' in relative.parts or path.suffix == '.pyc':
            continue
        if relative.parts[:3] == ('Lib', 'site-packages', 'bin'):
            continue  # pip-generated console scripts embed the build machine's paths.
        entries.append((path, 'python/' + relative.as_posix()))
    archive('python.zip', entries)
    for name in ('ffmpeg', 'ffprobe'):
        archive(name + '.zip', [
            (ffmpeg / 'bin' / (name + '.exe'), 'ffmpeg/' + name + '.exe'),
            (ffmpeg / 'LICENSE', 'ffmpeg/LICENSE'),
            (ffmpeg / 'README.txt', 'ffmpeg/README.txt'),
        ])
    distributions = importlib.metadata.distributions(path=[str(python / 'Lib' / 'site-packages')])
    lock = sorted(f'{d.metadata["Name"]}=={d.version}' for d in distributions)
    (output / 'requirements-lock.txt').write_text('\n'.join(lock) + '\n', encoding='utf-8')
    version = subprocess.check_output([str(python / 'python.exe'), '--version'], text=True).strip()
    ffversion = subprocess.check_output([str(ffmpeg / 'bin' / 'ffmpeg.exe'), '-version'], text=True).splitlines()[0]
    manifest = {'platform': 'windows-x64', 'python': version, 'ffmpeg': ffversion,
                'python_source': 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-embed-amd64.zip',
                'ffmpeg_source': 'https://github.com/FFmpeg/FFmpeg/commit/5fea5e3e11',
                'requirements_sha256': hashlib.sha256((root / 'requirements.txt').read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
                'packages': packages}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
