# Repair safe dependency installation, preserving the verified CUDA stack
import os, sys, subprocess, importlib
from pathlib import Path
ROOT=Path('/content/DATT')
os.chdir(ROOT)
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
p=ROOT/'scripts/colab_install.py'
s=p.read_text(encoding='utf-8-sig')
old="""    import socket
    for port in (8000, 8501):
        with socket.socket() as sock:
            if missing and sock.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError('Stop the owning service before installing missing dependencies')
"""
helper="""def listening_ports():
    import socket
    occupied = []
    for port in (8000, 8501):
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                occupied.append(port)
    return occupied


def stop_owned_service_for_install():
    ports = listening_ports()
    if not ports:
        return
    from src.ops import process
    with process.locked():
        record = process.state()
        if not process.owned(record):
            raise RuntimeError('Unverified service occupies DATT ports; no process stopped')
        import psutil
        listeners = [conn for conn in psutil.net_connections('tcp')
                     if conn.status == 'LISTEN' and conn.laddr.port in ports]
        if not listeners or any(conn.pid != record['pid'] for conn in listeners):
            raise RuntimeError('Port listener does not belong to verified DATT runner; no process stopped')
        try:
            process.stop(timeout=120)
        except TimeoutError:
            raise RuntimeError('Owned DATT service did not stop gracefully; no dependencies installed') from None
        if listening_ports():
            raise RuntimeError('DATT ports still occupied after owned service stopped')
    print('owned_backend_stopped_for_missing_dependencies=true', flush=True)


"""
if old in s:
    original=s
    s=s.replace(old, '    if missing:\n        stop_owned_service_for_install()\n',1)
    s=s.replace('def main():',helper+'def main():',1)
    needle='        if selected:\n'
    assert needle in s, 'Installer layout changed; review before patching'
    s=s.replace(needle,needle+'            stop_owned_service_for_install()\n',1)
    compile(s,str(p),'exec')
    backup=ROOT/'.datt-runtime/colab_install.before_owner_fix.py'
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists(): backup.write_text(original,encoding='utf-8')
    p.write_text(s,encoding='utf-8')
    print('INSTALLER_OWNER_FIX=APPLIED')
else:
    assert 'def stop_owned_service_for_install():' in s, 'Unknown installer version'
    print('INSTALLER_OWNER_FIX=ALREADY_PRESENT')
s=p.read_text(encoding='utf-8-sig')
needle='ROOT = Path(__file__).resolve().parents[1]'
if 'sys.path.insert(0, str(ROOT))' not in s:
    assert needle in s
    s=s.replace(needle,needle+'\nif str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))',1)
    compile(s,str(p),'exec')
    p.write_text(s,encoding='utf-8')
    print('INSTALLER_IMPORT_FIX=APPLIED')
q=ROOT/'requirements-agent.txt'
req=q.read_text()
if 'langchain-text-splitters' not in req: q.write_text(req.rstrip()+'\nlangchain-text-splitters>=0.3.0\n')
s=p.read_text()
s=s.replace("('agent', ('langchain-core>=0.3.0', 'langgraph>=0.2.0',","('agent', ('langchain-core>=0.3.0', 'langchain-text-splitters>=0.3.0', 'langgraph>=0.2.0',")
s=s.replace('import langchain_core, langgraph,', 'import langchain_core, langchain_text_splitters, langgraph,')
p.write_text(s)
s=p.read_text()
s=s.replace('assert any(r.path == "/api/agent/chat" for r in app.routes);', 'assert "post" in app.openapi()["paths"].get("/api/agent/chat", {});')
p.write_text(s)
importlib.invalidate_caches()
r=subprocess.run([sys.executable,'scripts/colab_install.py'],cwd=ROOT,capture_output=True,text=True,timeout=3000)
print(r.stdout)
for line in r.stderr.splitlines():
    if line.startswith(('ModuleNotFoundError:', 'ImportError:', 'NameError:', 'AttributeError:')): print(line)
print('DEPENDENCY_INSTALL_EXIT=',r.returncode)
assert r.returncode==0, 'Dependency setup failed; inspect private stage log'
