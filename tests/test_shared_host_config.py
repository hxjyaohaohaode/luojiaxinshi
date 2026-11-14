"""Exercise the real config verifier with a controlled Compose CLI boundary.

The normalized data below is synthetic, not a captured CI configuration.
compose-go UnitBytes.MarshalJSON emits decimal strings; an integer remains
accepted for compatible encoders. No Docker daemon or service is used here.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    'CAMPUS_PROJECT_NAME', 'CAMPUS_IMAGE', 'CAMPUS_ENV_FILE', 'APP_ORIGIN',
    'CAMPUS_TRUSTED_PROXY_IPS', 'CAMPUS_LOOPBACK_PORT', 'CAMPUS_MEMORY_LIMIT',
    'CAMPUS_CPU_LIMIT', 'CAMPUS_PIDS_LIMIT', 'CAMPUS_TMPFS_SIZE',
    'CAMPUS_LOG_MAX_SIZE', 'CAMPUS_LOG_MAX_FILES',
}
SERVICE = {
    'image': 'campus-config-fixture:synthetic', 'pull_policy': 'never',
    'user': '10001:10001', 'read_only': True, 'cap_drop': ['ALL'],
    'security_opt': ['no-new-privileges:true'],
    'mem_limit': '805306368', 'cpus': 0.5, 'pids_limit': 96,
    'tmpfs': ['/tmp:size=128m,mode=1777'],
    'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
    'environment': {'APP_ORIGIN': 'https://campus-fixture.example.invalid',
                    'FORWARDED_ALLOW_IPS': '198.51.100.10', 'APP_ENV': 'production',
                    'APP_HOST': '0.0.0.0', 'APP_PORT': '8765', 'DATA_DIR': '/data'},
    'healthcheck': {'test': ['CMD', 'python', '-c', "request('/api/health')"]},
    'volumes': [{'type': 'volume', 'source': 'campus-data', 'target': '/data'}],
    'networks': {'campus-private': None},
}


class ComposeCLI:
    def __init__(self, memory='805306368', cpu=0.5, render_failure=None, accept_missing=None):
        self.memory, self.cpu = memory, cpu
        self.render_failure, self.accept_missing = render_failure, accept_missing
        self.calls, self.outputs = [], {}

    def __call__(self, command, **options):
        self.calls.append(command)
        assert command[:2] == ['docker', 'compose']
        assert options['capture_output'] is True and options['text'] is True
        assert options['timeout'] == 30
        if command[2:] == ['version', '--short']:
            return subprocess.CompletedProcess(command, 0, 'v2.controlled-fixture\n', '')
        assert command[-3:] == ['config', '--format', 'json']
        environment = Path(command[command.index('--env-file') + 1])
        values = dict(line.split('=', 1) for line in environment.read_text().splitlines())
        label = environment.stem
        if label == self.render_failure:
            return subprocess.CompletedProcess(command, 2, '', 'controlled renderer syntax failure\n')
        missing = REQUIRED - values.keys()
        if missing and label != self.accept_missing:
            assert len(missing) == 1
            return subprocess.CompletedProcess(command, 1, '', 'required variable ' + next(iter(missing)))
        project = values.get('CAMPUS_PROJECT_NAME', 'campus-config-a')
        app = copy.deepcopy(SERVICE)
        app['mem_limit'], app['cpus'] = self.memory, self.cpu
        app['ports'] = [{'host_ip': '127.0.0.1', 'published': values.get('CAMPUS_LOOPBACK_PORT', '49123'),
                         'target': 8765, 'protocol': 'tcp'}]
        result = {'name': project, 'services': {'app': app},
                  'volumes': {'campus-data': {'name': project + '_campus-data'}},
                  'networks': {'campus-private': {'name': project + '_campus-private', 'driver': 'bridge',
                              'driver_opts': {'com.docker.network.bridge.gateway_mode_ipv4': 'nat'}}}}
        stdout = json.dumps(result)
        self.outputs[label] = stdout
        return subprocess.CompletedProcess(command, 0, stdout, '')


@pytest.fixture
def verifier():
    spec = importlib.util.spec_from_file_location('shared_host_verifier_under_test', ROOT / 'scripts/verify_shared_host_config.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def invoke(verifier, cli, monkeypatch, tmp_path):
    output = tmp_path / 'result.json'
    monkeypatch.setattr(verifier.subprocess, 'run', cli)
    monkeypatch.setattr(sys, 'argv', ['verify_shared_host_config.py', '--root', str(ROOT), '--output', str(output)])
    code = verifier.main()
    return code, json.loads(output.read_text())


@pytest.mark.parametrize('memory', ['805306368', 805306368], ids=['official-string', 'compatible-integer'])
def test_canonical_memory_budget_passes_every_configuration_case(verifier, monkeypatch, tmp_path, memory):
    cli = ComposeCLI(memory=memory)
    code, result = invoke(verifier, cli, monkeypatch, tmp_path)
    assert code == 0 and result['result'] == 'passed'
    assert result['configured_projects'] == 2 and result['missing_required_variables_rejected'] == 12
    assert len(result['checks']) == 14 and len(cli.calls) == 15
    assert result['services_started'] is False
    assert {item['case'] for item in result['checks']} == {'project-a', 'project-b'} | {'missing-' + name for name in REQUIRED}
    assert all(item['exit_code'] != 0 for item in result['checks'] if item['case'].startswith('missing-'))


@pytest.mark.parametrize('memory', [805306368.0, True, 536870912, '805306368.0'],
                         ids=['float-not-canonical', 'boolean', 'different-budget', 'noninteger-string'])
def test_invalid_memory_fails_and_keeps_original_rendered_values(verifier, monkeypatch, tmp_path, memory):
    cli = ComposeCLI(memory=memory)
    code, result = invoke(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed'
    assert result['services_started'] is False
    assert 'checks' in result, 'A failed config must retain completed renderer observations.'
    assert result['docker_compose_version'] == 'v2.controlled-fixture'
    assert len(result['checks']) == 2
    observed = result['checks'][0]
    assert observed['configuration']['services']['app']['mem_limit'] == memory
    assert observed['stdout'] == cli.outputs['project-a']


def test_changed_cpu_is_rejected_with_original_config_preserved(verifier, monkeypatch, tmp_path):
    cli = ComposeCLI(memory=805306368, cpu=1.0)
    code, result = invoke(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed'
    assert 'checks' in result, 'CPU failures must preserve actual rendered configuration.'
    assert result['checks'][0]['configuration']['services']['app']['cpus'] == 1.0
    assert result['checks'][0]['stdout'] == cli.outputs['project-a']
    assert '0.5' in result['error']


def test_renderer_failure_keeps_version_exit_code_and_exact_stderr(verifier, monkeypatch, tmp_path):
    cli = ComposeCLI(render_failure='project-a')
    code, result = invoke(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['services_started'] is False
    assert 'checks' in result, 'A failed renderer call must remain available for diagnosis.'
    assert result['docker_compose_version'] == 'v2.controlled-fixture'
    assert len(result['checks']) == 1
    assert result['checks'][0]['exit_code'] == 2
    assert result['checks'][0]['stderr'] == 'controlled renderer syntax failure\n'
    assert result['checks'][0]['stdout'] == ''
    assert 'configuration' not in result['checks'][0]


def test_silently_accepted_missing_variable_is_not_marked_passed(verifier, monkeypatch, tmp_path):
    cli = ComposeCLI(memory=805306368, accept_missing='missing-CAMPUS_CPU_LIMIT')
    code, result = invoke(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed'
    assert 'unexpectedly accepted a missing required variable' in result['error']
    assert 'checks' in result, 'The unexpected successful command must be retained.'
    row = result['checks'][-1]
    assert row['case'] == 'missing-CAMPUS_CPU_LIMIT' and row['exit_code'] == 0
    assert row['expected_success'] is False and row['stdout'] == cli.outputs[row['case']]
    assert result['services_started'] is False


def test_unavailable_docker_remains_a_nonzero_failure(verifier, monkeypatch, tmp_path):
    def unavailable(command, **options):
        assert command == ['docker', 'compose', 'version', '--short']
        raise FileNotFoundError('controlled unavailable docker executable')
    code, result = invoke(verifier, unavailable, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed'
    assert 'FileNotFoundError' in result['error'] and result['services_started'] is False
    assert not result.get('checks', [])


PROXY_REQUIRED = REQUIRED - {'CAMPUS_LOOPBACK_PORT'} | {'CAMPUS_PROXY_NETWORK'}


class ProxyComposeCLI(ComposeCLI):
    """Controlled JSON rendering; real network existence is deliberately untested."""

    def __init__(self, violation=None, accept_missing=None, network_fields=None):
        super().__init__(accept_missing=accept_missing)
        self.violation, self.inputs = violation, []
        self.network_fields = network_fields or {}

    def __call__(self, command, **options):
        if command == ['docker', 'compose', 'version', '--short']:
            return super().__call__(command, **options)
        self.calls.append(command)
        assert command[:2] == ['docker', 'compose']
        assert command[-3:] == ['config', '--format', 'json']
        assert Path(command[command.index('-f') + 1]).name == 'compose.proxy-network.yaml'
        assert options['capture_output'] is True and options['text'] is True and options['timeout'] == 30
        environment = Path(command[command.index('--env-file') + 1])
        values = dict(line.split('=', 1) for line in environment.read_text().splitlines())
        self.inputs.append(values)
        assert 'CAMPUS_LOOPBACK_PORT' not in values
        label = environment.stem
        missing = PROXY_REQUIRED - values.keys()
        if missing and label != self.accept_missing:
            assert len(missing) == 1
            return subprocess.CompletedProcess(command, 1, '', 'required variable ' + next(iter(missing)))
        project = values.get('CAMPUS_PROJECT_NAME', 'campus-config-a')
        app = copy.deepcopy(SERVICE)
        app['networks'] = {'campus-proxy': {'aliases': [project + '-app']}}
        result = {'name': project, 'services': {'app': app},
                  'volumes': {'campus-data': {'name': project + '_campus-data'}},
                  'networks': {'campus-proxy': {'external': True,
                               'name': values.get('CAMPUS_PROXY_NETWORK', 'campus-config-proxy')}}}
        result['networks']['campus-proxy'].update(copy.deepcopy(self.network_fields))
        if self.violation == 'published-port':
            app['ports'] = [{'host_ip': '0.0.0.0', 'published': '8765', 'target': 8765, 'protocol': 'tcp'}]
        elif self.violation == 'host-network':
            app['network_mode'] = 'host'
        elif self.violation == 'alias-collision' and label == 'project-b':
            app['networks']['campus-proxy']['aliases'] = ['campus-config-a-app']
        elif self.violation == 'data-volume-collision' and label == 'project-b':
            result['volumes']['campus-data']['name'] = 'campus-config-a_campus-data'
        elif self.violation == 'nonexternal-network':
            result['networks']['campus-proxy']['external'] = False
        elif self.violation == 'different-network':
            result['networks']['campus-proxy']['name'] = 'unrelated-project-database-network'
        stdout = json.dumps(result)
        self.outputs[label] = stdout
        return subprocess.CompletedProcess(command, 0, stdout, '')


def invoke_proxy(verifier, cli, monkeypatch, tmp_path):
    output = tmp_path / 'proxy-result.json'
    monkeypatch.setattr(verifier.subprocess, 'run', cli)
    monkeypatch.setattr(sys, 'argv', ['verify_shared_host_config.py', '--root', str(ROOT),
                                    '--mode', 'proxy-network', '--output', str(output)])
    code = verifier.main()
    return code, json.loads(output.read_text())


def test_proxy_network_mode_validates_two_projects_and_all_required_variables(verifier, monkeypatch, tmp_path):
    cli = ProxyComposeCLI()
    code, result = invoke_proxy(verifier, cli, monkeypatch, tmp_path)
    assert code == 0 and result['result'] == 'passed'
    assert result['mode'] == 'proxy-network' and result['template'] == 'compose.proxy-network.yaml'
    assert result['configured_projects'] == 2 and result['missing_required_variables_rejected'] == 12
    assert result['services_started'] is False and len(result['checks']) == 14 and len(cli.calls) == 15
    assert {row['case'] for row in result['checks']} == {'project-a', 'project-b'} | {'missing-' + name for name in PROXY_REQUIRED}
    assert all(row['exit_code'] != 0 for row in result['checks'][2:])
    first, second = [row['configuration'] for row in result['checks'][:2]]
    assert first['networks'] == second['networks'] == {'campus-proxy': {'external': True, 'name': 'campus-config-proxy'}}
    for config, project in [(first, 'campus-config-a'), (second, 'campus-config-b')]:
        app = config['services']['app']
        assert 'ports' not in app and app['networks']['campus-proxy']['aliases'] == [project + '-app']
        assert config['volumes']['campus-data']['name'] == project + '_campus-data'
    assert all('CAMPUS_LOOPBACK_PORT' not in values for values in cli.inputs)


@pytest.mark.parametrize('violation', ['published-port', 'host-network', 'alias-collision',
                                     'data-volume-collision', 'nonexternal-network', 'different-network'])
def test_proxy_network_mode_rejects_exposure_or_shared_identity(verifier, monkeypatch, tmp_path, violation):
    cli = ProxyComposeCLI(violation=violation)
    code, result = invoke_proxy(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed' and result['mode'] == 'proxy-network'
    assert result['services_started'] is False and result['error'].startswith('AssertionError')
    assert len(result['checks']) == 2 and len(cli.calls) == 3
    for record in result['checks']:
        assert record['stdout'] == cli.outputs[record['case']]
        assert record['configuration'] == json.loads(record['stdout'])


def test_proxy_network_mode_rejects_a_silently_defaulted_external_network(verifier, monkeypatch, tmp_path):
    cli = ProxyComposeCLI(accept_missing='missing-CAMPUS_PROXY_NETWORK')
    code, result = invoke_proxy(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed' and result['mode'] == 'proxy-network'
    assert 'unexpectedly accepted a missing required variable' in result['error']
    assert result['checks'][-1]['case'] == 'missing-CAMPUS_PROXY_NETWORK'
    assert result['checks'][-1]['exit_code'] == 0 and result['checks'][-1]['expected_success'] is False
    assert result['checks'][-1]['stdout'] == cli.outputs['missing-CAMPUS_PROXY_NETWORK']
    assert result['services_started'] is False


def test_proxy_network_mode_accepts_the_empty_ipam_normalization(verifier, monkeypatch, tmp_path):
    # Compose 5.1.3 emits this empty object for an external network; it does not
    # grant this project ownership of any IPAM settings or network lifecycle.
    cli = ProxyComposeCLI(network_fields={'ipam': {}})
    code, result = invoke_proxy(verifier, cli, monkeypatch, tmp_path)
    assert code == 0 and result['result'] == 'passed'
    assert result['configured_projects'] == 2 and result['missing_required_variables_rejected'] == 12
    assert len(result['checks']) == 14 and len(cli.calls) == 15 and result['services_started'] is False
    for row in result['checks'][:2]:
        assert row['configuration']['networks']['campus-proxy'] == {
            'name': 'campus-config-proxy', 'external': True, 'ipam': {}}
        assert row['stdout'] == cli.outputs[row['case']]
    assert all(row['exit_code'] != 0 for row in result['checks'][2:])


@pytest.mark.parametrize('network_fields', [
    {'ipam': {'driver': 'default'}},
    {'ipam': {'config': []}},
    {'ipam': {'config': [{'subnet': '192.0.2.0/24'}]}},
    {'ipam': None},
    {'ipam': []},
    {'ipam': {}, 'driver': 'bridge'},
    {'ipam': {}, 'config': []},
    {'ipam': {}, 'labels': {}},
], ids=['ipam-driver', 'ipam-empty-config', 'ipam-subnet', 'ipam-null',
        'ipam-array', 'network-driver', 'network-config', 'extra-network-key'])
def test_proxy_network_mode_rejects_managed_or_noncanonical_network_fields(verifier, monkeypatch, tmp_path, network_fields):
    cli = ProxyComposeCLI(network_fields=network_fields)
    code, result = invoke_proxy(verifier, cli, monkeypatch, tmp_path)
    assert code == 1 and result['result'] == 'failed' and result['mode'] == 'proxy-network'
    assert result['services_started'] is False and result['error'].startswith('AssertionError')
    assert 'pre-existing proxy network' in result['error']
    assert len(result['checks']) == 2 and len(cli.calls) == 3
    for row in result['checks']:
        assert row['stdout'] == cli.outputs[row['case']]
        network = row['configuration']['networks']['campus-proxy']
        for key, value in network_fields.items():
            assert network[key] == value
