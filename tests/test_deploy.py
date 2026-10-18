import pathlib
import subprocess
import tempfile
import os
import textwrap

workflow = pathlib.Path(__file__).resolve().parents[1] / '.github/workflows/laravel.yml'
source = workflow.read_text()
script = textwrap.dedent(source.split('      - name: Deploy\n        run: |\n', 1)[1])
assert '  workflow_call:' in source
assert '  push:' not in source
assert 'setfacl' not in source
assert 'rsync -rltz --no-perms --chmod=ugo=rwX' in source
assert subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True).returncode == 0
remote = script.split("<<'REMOTE'\n")[1].rsplit('\nREMOTE', 1)[0]
assert subprocess.run(['bash', '-n'], input=remote, text=True, capture_output=True).returncode == 0

for case in ['success','shared_vendor','upload_failure','migration_failure','activation_failure','restart_failure','collision','keep_one','keep_five','empty_hooks','before_multiline_failure','after_multiline_failure']:
  with tempfile.TemporaryDirectory() as td:
    base=pathlib.Path(td); project=base/'project'; binary=base/'bin'; binary.mkdir()
    (project/'.release-template/bootstrap/cache').mkdir(parents=True)
    (project/'shared/storage').mkdir(parents=True)
    (project/'shared/.env').write_text('SECRET=unchanged\n')
    (project/'shared/storage/upload').write_text('keep upload')
    (project/'releases/20261001000000_1/public').mkdir(parents=True)
    (project/'current').symlink_to(project/'releases/20261001000000_1')
    for n in ['20261002000000_2','gha-123-1-abcdef012345','20261003000000']:
      (project/'releases'/n).mkdir()
    if case=='shared_vendor':
      (project/'shared/vendor').mkdir()
      (project/'shared/vendor/autoload.php').write_text('shared vendor')
    rid='20261018123000'; release=project/'releases'/rid
    if case=='collision':
      release.mkdir(); (release/'sentinel').write_text('existing')
    files={
      'date':'#!/bin/bash\necho 20261018123000\n',
      'ssh':'#!/bin/bash\nwhile [[ \"$1\" == -* ]]; do shift 2; done\nshift\nif [[ "$1" == bash ]]; then exec "$@"; else exec bash -c "$1"; fi\n',
      'php':'#!/bin/bash\nif [[ "$*" == *"artisan queue:restart"* ]]; then [[ "$(readlink -f "$PROJECT_PATH/current")" == "$PWD" ]] || exit 45; echo restarted > "$PROJECT_PATH/restart-observed"; if [[ "$CASE" == restart_failure ]]; then exit 44; fi; fi\nif [[ "$CASE" == migration_failure && "$*" == *"artisan migrate"* ]]; then exit 42; fi\n',
      'mv':'#!/bin/bash\n/usr/bin/mv "$@" || exit $?\nif [[ "$CASE" == activation_failure ]]; then exit 43; fi\n',
      'rsync':'''#!/usr/bin/env python3
import os,pathlib,sys
if os.environ['CASE']=='upload_failure': sys.exit(23)
p=pathlib.Path(sys.argv[-1].split(':',1)[1]); (p/'public').mkdir(); (p/'vendor').mkdir(); (p/'vendor/autoload.php').write_text('built vendor'); (p/'bootstrap/cache').mkdir(parents=True, exist_ok=True)
'''
    }
    for name,content in files.items():
      p=binary/name; p.write_text(content); p.chmod(0o755)
    env=dict(os.environ,PATH=str(binary)+':'+os.environ['PATH'],CASE=case,DEPLOY_USER='deploy',DEPLOY_HOST='fake',PROJECT_PATH=str(project),DEPLOY_PORT='22',PHP_VERSION='8.5',KEEP_RELEASES='1' if case=='keep_one' else '5' if case=='keep_five' else '3',MOCK_PHP=str(binary/'php'))
    before='"$MOCK_PHP" artisan migrate --no-interaction'
    after='"$MOCK_PHP" artisan queue:restart --no-interaction'
    if case=='empty_hooks': before=after=''
    if case=='before_multiline_failure': before='echo "quoted value: \'literal\' $PWD" > "$PROJECT_PATH/hook-start"\nfalse\ntouch "$PROJECT_PATH/should-not-exist"'
    if case=='after_multiline_failure': after='false\ntouch "$PROJECT_PATH/should-not-exist"'
    env.update(BEFORE_ACTIVATION=before, AFTER_ACTIVATION=after)
    result=subprocess.run(['bash'],input=script.replace('php="/usr/bin/php$3"', 'php="$MOCK_PHP"'),text=True,capture_output=True,env=env)
    expected={'success':0,'shared_vendor':0,'upload_failure':23,'migration_failure':42,'activation_failure':43,'restart_failure':44,'collision':1,'keep_one':0,'keep_five':0,'empty_hooks':0,'before_multiline_failure':1,'after_multiline_failure':1}[case]
    assert result.returncode==expected,(case,result.returncode,result.stderr)
    switched=case in ['success','shared_vendor','activation_failure','restart_failure','keep_one','keep_five','empty_hooks','after_multiline_failure']
    assert (project/'current').resolve()==(release if switched else project/'releases/20261001000000_1'),case
    assert (project/'shared/.env').read_text()=='SECRET=unchanged\n'
    assert (project/'shared/storage/upload').read_text()=='keep upload'
    assert not (project/'should-not-exist').exists(),case
    if case in ['upload_failure','migration_failure','before_multiline_failure']:
      assert not release.exists(),case
    if case=='collision': assert (release/'sentinel').read_text()=='existing'
    assert (project/'restart-observed').exists() == (case in ['success','shared_vendor','restart_failure','keep_one','keep_five']),case
    if case in ['success','shared_vendor','keep_one','keep_five','empty_hooks']:
      assert len(list((project/'releases').iterdir()))==int(env['KEEP_RELEASES'])
      assert (release/'.env').resolve()==project/'shared/.env'
      assert (release/'storage').resolve()==project/'shared/storage'
      assert (release/'vendor/autoload.php').read_text()==('shared vendor' if case=='shared_vendor' else 'built vendor')
    print('PASS',case)
print('PASS workflow and remote Bash syntax')
