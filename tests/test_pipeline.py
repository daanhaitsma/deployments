import os
from pathlib import Path
import subprocess
import tempfile
import textwrap

source = (Path(__file__).resolve().parents[1] / '.github/workflows/laravel.yml').read_text()
install = textwrap.dedent(source.split('      - name: Install dependencies\n', 1)[1].split('        run: |\n', 1)[1].split('\n      - uses:', 1)[0])
assert source.index('uses: actions/cache/save@v5') < source.index('composer install --no-dev')
assert "hashFiles('composer.lock', 'composer.json', 'package-lock.json', 'package.json')" in source
assert 'steps.runtime.outputs.php' in source and 'steps.runtime.outputs.node' in source

for hit in ['true', 'false']:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for command in ['composer', 'npm']:
            executable = root / command
            executable.write_text('#!/bin/bash\necho "${0##*/} $*" >> "$COMMAND_LOG"\n')
            executable.chmod(0o755)
        log = root / 'commands'
        env = dict(os.environ, PATH=f'{root}:' + os.environ['PATH'], CACHE_HIT=hit, COMMAND_LOG=str(log))
        subprocess.run(['bash', '-euo', 'pipefail'], input=install, text=True, env=env, check=True)
        commands = log.read_text()
        assert 'composer install' in commands
        assert ('npm ci' in commands) == (hit == 'false')
        print('PASS dependencies cache-hit=' + hit)

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
