"""Package source + local edits for a fresh Colab without committing/pushing."""
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                    cwd=ROOT, timeout=15).decode().split('\0')
    destination = ROOT / '.datt-runtime/datt-source.zip'
    destination.parent.mkdir(exist_ok=True)
    directories = {'src', 'scripts', 'configs', 'tests'}
    extensions = {'.py', '.yaml', '.yml', '.json', '.ini', '.html', '.css', '.js', '.svg', '.txt', '.ico'}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(set(paths)):
            path = Path(name)
            if not name or not (ROOT / path).is_file() or (ROOT / path).is_symlink():
                continue
            include = (path.parts[0] in directories and path.suffix in extensions or
                       path.parent == Path('.') and (path.name in ('app.py', 'config.py') or path.name.startswith('requirements') and path.suffix == '.txt'))
            if include:
                archive.write(ROOT / path, name)
    print('source_archive=' + str(destination))
    print('Secrets, databases, media and model weights are excluded.')


if __name__ == '__main__':
    main()
