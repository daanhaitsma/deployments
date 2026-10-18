import getpass
import os
from pathlib import Path
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True)


def effective(path, user):
    acl = run('getfacl', '-cp', str(path))
    entries = dict(line.split('\t', 1)[0].split(':', 2)[1:]
                   for line in acl.splitlines()
                   if line.startswith('user:') and not line.startswith('user::'))
    mask = next(line.split(':')[2] for line in acl.splitlines() if line.startswith('mask::'))
    return set(entries[user].strip()) & set(mask) - {'-'}


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    template = root / '.release-template'
    cache = template / 'bootstrap/cache'
    cache.mkdir(parents=True)
    user = getpass.getuser()
    read_acl = f'u::rwx,u:{user}:rwx,u:www-data:r-x,g::---,m::rwx,o::---'
    for directory in [template, template / 'bootstrap']:
        run('setfacl', '-m', read_acl, str(directory))
        run('setfacl', '-d', '-m', read_acl, str(directory))
    write_acl = f'u::rwx,u:{user}:rwx,u:www-data:rwx,g::---,m::rwx,o::---'
    run('setfacl', '-m', write_acl, str(cache))
    run('setfacl', '-d', '-m', write_acl, str(cache))
    release = root / 'release'
    release.mkdir()
    run('cp', '-a', str(template) + '/.', str(release) + '/')
    source = root / 'source'
    (source / 'bootstrap/cache').mkdir(parents=True)
    (source / 'app').mkdir()
    (source / 'app/code.php').write_text('<?php')
    (source / 'app/code.php').chmod(0o600)
    (source / 'bootstrap/cache/.gitignore').write_text('*')
    (source / 'bootstrap/cache/.gitignore').chmod(0o600)
    run('rsync', '-rltz', '--no-perms', '--chmod=ugo=rwX', str(source) + '/', str(release) + '/')
    assert effective(release / 'app', 'www-data') == {'r', 'x'}
    assert effective(release / 'app/code.php', 'www-data') == {'r'}
    assert effective(release / 'bootstrap/cache', 'www-data') == {'r', 'w', 'x'}
    assert effective(release / 'bootstrap/cache/.gitignore', 'www-data') == {'r', 'w'}
    (release / 'bootstrap/cache/config.php').write_text('<?php')
    assert effective(release / 'bootstrap/cache/config.php', 'www-data') == {'r', 'w'}
print('PASS real ACL inheritance, cp template and rsync: code read-only, runtime writable')
