"""Explicit dependency provisioning; preserves Colab Torch and verified ORT versions."""
import importlib.metadata as metadata
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for port in (8000, 8501):
        with socket.socket() as sock:
            sock.settimeout(2)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Stop backend before installing dependencies')
    constraints = ROOT / '.colab-persistence-constraints.txt'
    constraints.write_text('\n'.join(name + '==' + metadata.version(name)
                          for name in ('torch', 'torchvision')) + '\nonnxruntime-gpu==1.26.0\n')
    commands = [
        [sys.executable, '-m', 'pip', 'install', '-c', str(constraints), '-r', 'requirements-colab.txt', '-r', 'requirements-cli.txt'],
        [sys.executable, '-m', 'pip', 'uninstall', '-y', 'onnxruntime', 'onnxruntime-gpu'],
        [sys.executable, '-m', 'pip', 'install', '--no-deps', 'onnxruntime-gpu==1.26.0'],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True, timeout=1200)


if __name__ == '__main__':
    main()
