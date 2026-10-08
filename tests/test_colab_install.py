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
    assert {'langchain-core', 'langgraph', 'langgraph-checkpoint-postgres', 'psycopg-pool',
            'fastembed', 'langchain-google-genai', 'langchain-openai'} <= names
