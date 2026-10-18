import os
from pathlib import Path
import subprocess
import tempfile
import textwrap

source = (Path(__file__).resolve().parents[1] / '.github/workflows/laravel.yml').read_text()
install = textwrap.dedent(source.split('      - name: Install dependencies\n', 1)[1].split('        run: |\n', 1)[1].split('\n      - uses:', 1)[0])
pipeline = textwrap.dedent(source.split('      - name: Test and build\n', 1)[1].split('        run: |\n', 1)[1].split('\n      - uses:', 1)[0])
defaults = source.split('      install-commands:\n', 1)[1].split('      test-commands:', 1)[0]
default_install = textwrap.dedent(defaults.split('        default: |\n', 1)[1])
default_after = source.split('      after-test-commands:\n', 1)[1].split('        default: ', 1)[1].split('\n', 1)[0]
assert source.index('uses: actions/cache/save@v5') < source.index('- name: Test and build')
assert "hashFiles('composer.lock', 'composer.json', 'package-lock.json', 'package.json')" in source
assert 'steps.runtime.outputs.php' in source and 'steps.runtime.outputs.node' in source
assert 'steps.runtime.outputs.install' in source

runtime = textwrap.dedent(source.split('      - name: Runtime cache key\n', 1)[1].split('        run: |\n', 1)[1].split('\n      - uses:', 1)[0])
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    keys = []
    for commands in [default_install, 'npm ci', '']:
        output = root / str(len(keys))
        env = dict(os.environ, INSTALL_COMMANDS=commands, GITHUB_OUTPUT=str(output))
        subprocess.run(['bash', '-euo', 'pipefail'], input=runtime, text=True, env=env, check=True)
        keys.append(next(line for line in output.read_text().splitlines() if line.startswith('install=')))
    assert len(set(keys)) == 3
    print('PASS dependency command changes invalidate cache')

for hit in ['true', 'false']:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for command in ['composer', 'npm']:
            executable = root / command
            executable.write_text('#!/bin/bash\necho "${0##*/} $*" >> "$COMMAND_LOG"\n')
            executable.chmod(0o755)
        log = root / 'commands'
        env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], CACHE_HIT=hit, COMMAND_LOG=str(log), INSTALL_COMMANDS=default_install)
        subprocess.run(['bash', '-euo', 'pipefail'], input=install, text=True, env=env, check=True)
        commands = log.read_text()
        assert 'composer install' in commands
        assert ('npm ci' in commands) == (hit == 'false')
        print('PASS dependencies cache-hit=' + hit)

for case in ['defaults', 'static', 'custom', 'install_failure', 'test_failure', 'cleanup_failure', 'pipeline_failure']:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for command in ['composer', 'npm']:
            executable = root / command
            executable.write_text('#!/bin/bash\nprintf "%s\\n" "${0##*/} $*" >> "$COMMAND_LOG"\n')
            executable.chmod(0o755)
        log = root / 'commands'
        install_commands = default_install
        tests = 'echo tested >> "$COMMAND_LOG"'
        after = default_after
        if case == 'static':
            install_commands = after = ''
        elif case == 'custom':
            install_commands = 'printf "%s\\n" \'custom install: "quoted"\' >> "$COMMAND_LOG"'
            after = 'printf "%s\\n" \'custom cleanup: $literal\' >> "$COMMAND_LOG"'
        elif case == 'install_failure':
            install_commands = 'exit 17\necho should-not-run >> "$COMMAND_LOG"'
        elif case == 'test_failure':
            tests = 'exit 18\necho should-not-run >> "$COMMAND_LOG"'
        elif case == 'cleanup_failure':
            after = 'exit 19\necho should-not-run >> "$COMMAND_LOG"'
        elif case == 'pipeline_failure':
            install_commands = 'false | cat\necho should-not-run >> "$COMMAND_LOG"'
        env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], CACHE_HIT='false', COMMAND_LOG=str(log), INSTALL_COMMANDS=install_commands, TEST_COMMANDS=tests, AFTER_TEST_COMMANDS=after)
        result = subprocess.run(['bash', '-euo', 'pipefail'], input=install + '\n' + pipeline, cwd=root, text=True, env=env, capture_output=True)
        expected = {'install_failure': 17, 'test_failure': 18, 'cleanup_failure': 19, 'pipeline_failure': 1}.get(case, 0)
        assert result.returncode == expected, (case, result.stderr)
        commands = log.read_text() if log.exists() else ''
        assert 'should-not-run' not in commands
        if case == 'defaults':
            assert commands.splitlines() == ['composer install --prefer-dist --no-progress', 'npm ci', 'tested', default_after]
        elif case == 'static':
            assert commands.splitlines() == ['tested']
        elif case == 'custom':
            assert commands.splitlines() == ['custom install: "quoted"', 'tested', 'custom cleanup: $literal']
        elif case in ['install_failure', 'pipeline_failure']:
            assert 'tested' not in commands
        elif case == 'test_failure':
            assert '--no-dev' not in commands
        print('PASS configurable pipeline ' + case)

# This is the project-supplied parallel test pattern; both failures must propagate.
parallel = '''
npm test &
frontend=$!
php artisan test --compact &
backend=$!
status=0
wait "$frontend" || status=1
wait "$backend" || status=1
exit "$status"
'''
for frontend, backend in [(0, 0), (1, 0), (0, 1), (1, 1)]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for command, status in [('npm', frontend), ('php', backend)]:
            executable = root / command
            executable.write_text(f'#!/bin/bash\ntouch "$COMMAND_LOG/{command}-started"\nwhile [[ ! -f "$COMMAND_LOG/npm-started" || ! -f "$COMMAND_LOG/php-started" ]]; do sleep 0.01; done\nexit {status}\n')
            executable.chmod(0o755)
        env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], COMMAND_LOG=str(root))
        result = subprocess.run(['bash', '-euo', 'pipefail'], input=parallel, text=True, env=env, timeout=5)
        assert result.returncode == int(bool(frontend or backend))
        print(f'PASS parallel tests frontend={frontend}, backend={backend}')
