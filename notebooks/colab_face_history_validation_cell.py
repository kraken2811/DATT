"""Paste into Colab after uploading scratch/agent-face-history-colab-final.zip.

Verifies only the Agent patch with disposable mock fixtures. No local .env,
production credentials, recognition records, or model assets are transferred.
"""
import hashlib
import io
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path('/content/DATT')
PACKAGE_NAME = 'agent-face-history-colab-final.zip'
EXPECTED_SHA256 = 'da8ced8749152d7d191809626972cf376accb3d1447fb5b115418309f6d52c5b'
ALLOWED = {
    'src/agent/face_history.py', 'src/agent/nodes.py', 'src/agent/graph.py',
    'src/agent/prompts.py', 'src/agent/response_formatting.py',
    'src/agent/tools/watchlist.py', 'src/agent/tools/events.py',
    'tests/test_agent_face_history.py', 'scripts/validate_agent_responses.py',
}
assert ROOT.is_dir(), 'DATT checkout missing; run the source/dependency cells first'
package = next((p for p in (Path('/content') / PACKAGE_NAME, ROOT / PACKAGE_NAME) if p.is_file()), None)
assert package is not None, 'Upload the FINAL local ZIP using the Colab Files pane first'
payload = package.read_bytes()
assert hashlib.sha256(payload).hexdigest() == EXPECTED_SHA256, 'Source package mismatch: upload the latest ZIP'
backup = ROOT / '.datt-runtime/face-history-backup'
with zipfile.ZipFile(io.BytesIO(payload)) as archive:
    assert set(archive.namelist()) == ALLOWED, 'Unexpected source file'
    for name in archive.namelist():
        target = ROOT / name
        prior = backup / name
        if target.exists() and not prior.exists():
            prior.parent.mkdir(parents=True, exist_ok=True)
            prior.write_bytes(target.read_bytes())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
print('FINAL_FACE_HISTORY_SOURCE_PACKAGE=VERIFIED')
print('COLAB_TEST_LLM_PROVIDER=mock; API_KEYS=disabled; DATABASE=disposable_SQLite')
result = subprocess.run(
    [sys.executable, 'scripts/validate_agent_responses.py'], cwd=ROOT,
    capture_output=True, text=True, timeout=300,
)
log = ROOT / '.datt-runtime/face-history-tests.log'
log.parent.mkdir(parents=True, exist_ok=True)
log.write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
for line in result.stdout.splitlines():
    if re.search(r'\d+ (?:passed|failed|skipped)|ERROR|FAILURES', line):
        print(line)
print('COLAB_AGENT_FACE_HISTORY_EXIT=' + str(result.returncode))
assert result.returncode == 0, 'Agent regression failed; inspect the isolated test log'
