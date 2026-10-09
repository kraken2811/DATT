"""Colab dependency resolution regressions; no network or package mutations."""
import types
import pytest
from scripts import colab_install as install


def test_active_metadata_wins_over_shadowed_distribution(monkeypatch):
    monkeypatch.setattr(install.metadata, 'distributions', lambda: [
        types.SimpleNamespace(metadata={'Name': 'numpy'}, version='2.1.3'),
        types.SimpleNamespace(metadata={'Name': 'numpy'}, version='1.26.4')])
    monkeypatch.setattr(install.metadata, 'version', lambda name: '2.1.3')
    assert install.active_versions() == {'numpy': '2.1.3'}


def report(name, version, suffix='.whl'):
    return {'install': [{'metadata': {'name': name, 'version': version},
                         'download_info': {'url': 'https://files.pythonhosted.org/pkg' + suffix}}]}


@pytest.mark.parametrize('name,version,installed,suffix', [
    ('torch', '2.12.0', {}, '.whl'),
    ('numpy', '1.26.4', {'numpy': '2.1.3'}, '.whl'),
    ('onnxruntime', '1.26.0', {}, '.whl'),
    ('onnx', '1.20.1', {}, '.tar.gz'),
])
def test_unsafe_resolver_plans_are_rejected(name, version, installed, suffix):
    with pytest.raises(RuntimeError):
        install.audit_plan(report(name, version, suffix), installed)


def test_missing_gpu_wheel_is_allowed():
    assert install.audit_plan(report('onnxruntime_gpu', '1.26.0'), {}) == {'onnxruntime-gpu': '1.26.0'}


def test_gpu_ort_substitution_checks_transitive_dependencies(monkeypatch):
    monkeypatch.setattr(install, 'STAGES', (('face', ('insightface',)),))
    versions = {'insightface': '2.0', 'onnxruntime-gpu': '1.26.0', 'numpy': '2.1.3'}
    deps = {'insightface': ['onnxruntime>=1.20'], 'onnxruntime-gpu': ['numpy>=2'], 'numpy': []}
    monkeypatch.setattr(install.metadata, 'version', versions.__getitem__)
    monkeypatch.setattr(install.metadata, 'requires', deps.__getitem__)
    install.validate_dependencies()
    versions['numpy'] = '1.26.4'
    with pytest.raises(RuntimeError, match='numpy'):
        install.validate_dependencies()



def test_fastembed_uses_gpu_ort_without_losing_other_dependencies():
    deps = install.embedding_dependencies(['onnxruntime>=1.21', 'tokenizers>=0.15',
                                          'unused; extra == "optional"'])
    assert deps == ['onnxruntime-gpu>=1.21', 'tokenizers>=0.15']


def test_agent_dependencies_are_provisioned():
    names = {install.Requirement(name).name for _, stage in install.STAGES for name in stage}
    assert {'langchain-core', 'langchain-text-splitters', 'langgraph', 'langgraph-checkpoint-postgres', 'psycopg-pool',
            'fastembed', 'langchain-google-genai', 'langchain-openai'} <= names



def test_install_does_not_stop_service_when_ports_are_free(monkeypatch):
    from src.ops import process
    monkeypatch.setattr(install, 'listening_ports', lambda: [])
    monkeypatch.setattr(process, 'stop', lambda **kwargs: pytest.fail('must not stop'))
    install.stop_owned_service_for_install()


def service_fixture(monkeypatch, owned, ports):
    from contextlib import nullcontext
    from src.ops import process
    import psutil
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [
        types.SimpleNamespace(status='LISTEN', laddr=types.SimpleNamespace(port=port), pid=42)
        for port in ports[0]])
    monkeypatch.setattr(process, 'locked', nullcontext)
    monkeypatch.setattr(process, 'state', lambda: {'pid': 42})
    monkeypatch.setattr(process, 'owned', lambda record: owned)
    states = iter(ports)
    monkeypatch.setattr(install, 'listening_ports', lambda: next(states))
    calls = []
    monkeypatch.setattr(process, 'stop', lambda **kwargs: calls.append(kwargs))
    return calls


def test_direct_installer_stops_verified_service(monkeypatch):
    calls = service_fixture(monkeypatch, True, [[8000, 8501], []])
    install.stop_owned_service_for_install()
    assert calls == [{'timeout': 120}]


def test_direct_installer_does_not_stop_unverified_listener(monkeypatch):
    calls = service_fixture(monkeypatch, False, [[8501]])
    with pytest.raises(RuntimeError, match='Unverified service.*8501'):
        install.stop_owned_service_for_install()
    assert calls == []


def test_direct_installer_rechecks_ports_after_stop(monkeypatch):
    calls = service_fixture(monkeypatch, True, [[8000, 8501], [8000]])
    with pytest.raises(RuntimeError, match='still occupied.*8000'):
        install.stop_owned_service_for_install()
    assert calls == [{'timeout': 120}]


def test_direct_installer_does_not_install_after_shutdown_timeout(monkeypatch):
    from src.ops import process
    service_fixture(monkeypatch, True, [[8501]])
    def timeout(**kwargs):
        raise TimeoutError()
    monkeypatch.setattr(process, 'stop', timeout)
    with pytest.raises(RuntimeError, match='did not stop gracefully'):
        install.stop_owned_service_for_install()


@pytest.mark.parametrize('missing', [[], ['missing-package']])
def test_installer_checks_service_before_any_package_mutation(monkeypatch, tmp_path, missing):
    monkeypatch.setattr(install, 'ROOT', tmp_path)
    monkeypatch.setattr(install, 'STAGES', (('backend', ('missing-package',)),))
    monkeypatch.setattr(install, 'active_versions', lambda: dict(install.TORCH))
    monkeypatch.setattr(install, 'cuda_torch_ready', lambda: True)
    monkeypatch.setattr(install, 'plan', lambda: (missing, []))
    def stop():
        raise RuntimeError('unverified-test-listener')
    monkeypatch.setattr(install, 'stop_owned_service_for_install', stop)
    def pip(args, label, logdir):
        assert '--dry-run' in args, 'No actual install allowed while a listener is unverified'
        import json
        (logdir / 'backend-plan.json').write_text(json.dumps(report('missing-package', '1.0')))
    monkeypatch.setattr(install, 'run_pip', pip)
    with pytest.raises(RuntimeError, match='unverified-test-listener'):
        install.main()



def test_verified_runner_is_not_stopped_for_another_process_listener(monkeypatch):
    import psutil
    calls = service_fixture(monkeypatch, True, [[8501]])
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [
        types.SimpleNamespace(status='LISTEN', laddr=types.SimpleNamespace(port=8501), pid=99)])
    with pytest.raises(RuntimeError, match='does not belong'):
        install.stop_owned_service_for_install()
    assert calls == []


def test_direct_script_can_import_checkout_modules(tmp_path):
    import subprocess
    import sys
    code = (
        "import runpy, sys; from pathlib import Path; "
        "root = Path(sys.argv[1]).resolve().parents[1]; "
        "sys.path = [p for p in sys.path if p and Path(p).resolve() != root]; "
        "ns = runpy.run_path(sys.argv[1], run_name='installer_probe'); "
        "from src.ops import process; "
        "assert process.__file__ is not None"
    )
    result = subprocess.run(
        [sys.executable, '-c', code, str(install.ROOT / 'scripts/colab_install.py')],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
