"""Deployment gates evaluated locally with fake processes; never a Colab execution claim."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'notebooks/colab_latest_dev_verification.py'
NOTEBOOK = ROOT / 'notebooks/DATT_Latest_DEV_Verification.ipynb'
APPROVED = 'a' * 40


@pytest.fixture
def deployment(tmp_path):
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    definitions = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))]
    ns = {}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(SCRIPT), 'exec'), ns)
    checkout = tmp_path.resolve()
    (checkout / '.git').mkdir()
    ns.update(ROOT=checkout, REMOTE='https://github.com/kraken2811/DATT.git', PORT=8501, MODE='api',
              APPROVED_SOURCE_COMMIT=APPROVED, RESULT={'stages': {'environment': 'PASS'}},
              DATABASE_IDENTITY_CONFIRMED=True, RECOVERY_POINT_CONFIRMED=True)
    responses = {('rev-parse', '--show-toplevel'): str(checkout), ('rev-parse', 'HEAD'): 'b' * 40,
        ('branch', '--show-current'): 'dev', ('remote', 'get-url', 'origin'): ns['REMOTE'],
        ('status', '--short'): '', ('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev'): '',
        ('rev-parse', 'origin/dev'): APPROVED}
    ns['git'] = Mock(side_effect=lambda *args: responses[args])
    for name in ('command', 'cli', 'occupied'):
        ns[name] = Mock(side_effect=AssertionError('Blocked gate attempted a process/service operation'))
    return ns, responses


def test_notebook_twelve_unexecuted_cells_match_script():
    cells = [c for c in json.loads(NOTEBOOK.read_text(encoding='utf-8'))['cells'] if c['cell_type'] == 'code']
    assert len(cells) == 12
    assert ''.join(''.join(c['source']) for c in cells) == SCRIPT.read_text(encoding='utf-8')
    for number, cell in enumerate(cells, 1):
        assert cell['execution_count'] is None and cell['outputs'] == []
        compile(''.join(cell['source']), f'cell-{number}', 'exec')


def test_dirty_checkout_never_fetches_or_stops_service(deployment):
    ns, responses = deployment
    responses[('status', '--short')] = ' M src/agent/nodes.py\n?? runtime-patch.py'
    with pytest.raises(ns['Blocked'], match='DIRTY_CHECKOUT'):
        ns['sync_source']()
    assert not any(c.args[0] == 'fetch' for c in ns['git'].call_args_list)
    ns['cli'].assert_not_called()
    ns['command'].assert_not_called()


@pytest.mark.parametrize('approved', [None, '', '900d561', 'not-a-reviewed-revision'])
def test_unapproved_revision_never_fetches_or_deploys(deployment, approved):
    ns, _ = deployment
    ns['APPROVED_SOURCE_COMMIT'] = approved
    with pytest.raises(ns['Blocked'], match='APPROVED_COMMIT_REQUIRED'):
        ns['sync_source']()
    ns['git'].assert_not_called()
    ns['cli'].assert_not_called()
    ns['command'].assert_not_called()


def test_latest_dev_mismatch_leaves_owned_service_and_checkout_untouched(deployment):
    ns, responses = deployment
    responses[('rev-parse', 'origin/dev')] = 'c' * 40
    with pytest.raises(ns['Blocked'], match='REMOTE_DEV_NOT_APPROVED'):
        ns['sync_source']()
    ns['git'].assert_any_call('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
    ns['cli'].assert_not_called()
    ns['command'].assert_not_called()


@pytest.mark.parametrize('gate', ['source', 'dependencies', 'isolated_tests', 'configuration', 'database', 'agent'])
def test_any_failed_gate_blocks_doctor_and_start(deployment, gate):
    ns, _ = deployment
    ns['RESULT']['stages'] = {n: 'PASS' for n in ('source', 'dependencies', 'isolated_tests', 'configuration', 'database', 'agent')}
    ns['RESULT']['stages'][gate] = 'FAIL: simulated regression'
    with pytest.raises(ns['Blocked'], match='DEPLOYMENT_GATES_NOT_PASSED'):
        ns['start_application']()
    ns['cli'].assert_not_called()


@pytest.mark.parametrize('confirmation', ['DATABASE_IDENTITY_CONFIRMED', 'RECOVERY_POINT_CONFIRMED'])
def test_missing_recovery_confirmation_blocks_storage_probe_and_start(deployment, confirmation):
    ns, _ = deployment
    ns['RESULT']['stages'] = {n: 'PASS' for n in ('source', 'dependencies', 'isolated_tests', 'configuration', 'database', 'agent')}
    ns[confirmation] = False
    with pytest.raises(ns['Blocked'], match='DB_RECOVERY_CONFIRMATION_REQUIRED'):
        ns['start_application']()
    ns['cli'].assert_not_called()


def test_unknown_listener_is_never_stopped(deployment):
    ns, _ = deployment
    ns['ROOT'] = ns['ROOT'] / 'missing-checkout'
    ns['command'] = Mock(return_value=type('Process', (), {'returncode': 0, 'stdout': APPROVED + '\trefs/heads/dev'})())
    ns['occupied'] = Mock(return_value=True)
    with pytest.raises(ns['Blocked'], match='UNKNOWN_LISTENER'):
        ns['sync_source']()
    ns['cli'].assert_not_called()
    assert ns['command'].call_count == 1


def test_failed_agent_gate_never_imports_or_initializes_live_provider(deployment):
    ns, _ = deployment
    ns['RESULT']['stages']['source'] = 'PASS'
    ns['RESULT']['stages']['configuration'] = 'PASS'
    ns['RESULT']['stages']['isolated_tests'] = 'FAIL: regression'
    with pytest.raises(ns['Blocked'], match='REGRESSION_FAILURES_BLOCK_STARTUP'):
        ns['inspect_agent']()
    ns['command'].assert_not_called()


@pytest.mark.parametrize('change', ['dirty', 'head', 'remote'])
def test_source_change_after_tests_prevents_doctor_or_start(deployment, change):
    ns, responses = deployment
    ns['RESULT'].update(source_commit=APPROVED)
    ns['RESULT']['stages'] = {n: 'PASS' for n in ('source', 'dependencies', 'isolated_tests', 'configuration', 'database', 'agent')}
    responses[('rev-parse', 'HEAD')] = APPROVED
    if change == 'dirty':
        responses[('status', '--short')] = ' M src/agent/nodes.py'
    elif change == 'head':
        responses[('rev-parse', 'HEAD')] = 'b' * 40
    else:
        responses[('rev-parse', 'origin/dev')] = 'c' * 40
    with pytest.raises(ns['Blocked'], match='AFTER_TESTS'):
        ns['start_application']()
    ns['cli'].assert_not_called()


def test_failed_regressions_are_counted_and_block_deployment(deployment):
    ns, _ = deployment
    ns['RESULT']['stages']['source'] = 'PASS'
    def fake_tests(args, **kwargs):
        xml_path = Path(next(a.split('=', 1)[1] for a in args if a.startswith('--junitxml=')))
        xml_path.write_text('<testsuite><testcase classname="fixture" name="pass"/>'
                            '<testcase classname="fixture" name="failure"><failure/></testcase></testsuite>')
        return type('Run', (), {'stdout': 'fixture failure', 'stderr': '', 'returncode': 1})()
    ns['command'] = Mock(side_effect=fake_tests)
    with pytest.raises(ns['Blocked'], match='REGRESSIONS_FAILED'):
        ns['test_suites']()
    assert ns['command'].call_count == 2
    assert all(s['passed'] == 1 and s['failed'] == 1 and s['exit'] == 1 for s in ns['RESULT']['tests'].values())


def test_file_execution_reports_blocked_deployment_with_nonzero_exit(deployment):
    ns, _ = deployment
    ns['sys'] = SimpleNamespace(argv=['colab_latest_dev_verification.py'])
    exit_gate = ast.parse(SCRIPT.read_text(encoding='utf-8')).body[-1]
    with pytest.raises(SystemExit) as error:
        exec(compile(ast.Module(body=[exit_gate], type_ignores=[]), 'deployment-exit', 'exec'), ns)
    assert error.value.code == 1


def test_blocked_interactive_notebook_retains_its_kernel(deployment):
    ns, _ = deployment
    ns['sys'] = SimpleNamespace(argv=['ipykernel_launcher.py'])
    exit_gate = ast.parse(SCRIPT.read_text(encoding='utf-8')).body[-1]
    exec(compile(ast.Module(body=[exit_gate], type_ignores=[]), 'notebook-exit', 'exec'), ns)
