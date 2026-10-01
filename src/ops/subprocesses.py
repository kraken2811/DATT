"""Bound subprocess trees, including Windows venv launcher grandchildren."""
import subprocess


def run_bounded(args, *, timeout, cwd=None, env=None, capture_output=False, text=True):
    import psutil
    child = subprocess.Popen(args, cwd=cwd, env=env, text=text,
                             stdout=subprocess.PIPE if capture_output else None,
                             stderr=subprocess.PIPE if capture_output else None)
    owner = psutil.Process(child.pid)
    try:
        stdout, stderr = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            descendants = owner.children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        # These handles refer only to descendants of the subprocess we created.
        for process in reversed(descendants):
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        child.kill()
        child.communicate(timeout=5)
        psutil.wait_procs(descendants, timeout=5)
        raise subprocess.TimeoutExpired(args, timeout) from None
    return subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
