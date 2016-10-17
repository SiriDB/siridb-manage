#!/usr/bin/python3

import sys
import os
import datetime
import platform
import subprocess
import shutil
import stat
import re

from version import __version__



def _get_changelog(version):
    with open('ChangeLog-{}'.format(version), 'r') as f:
        content = f.read()
    return content

def _get_distribution():
    '''Returns distribution code name. (Ubuntu)'''
    proc = subprocess.Popen(['lsb_release', '-c'], stdout=subprocess.PIPE)
    for line in proc.stdout:
        if line:
            return line.decode().split('\t')[1].strip()


if __name__ == '__main__':
    # Run setup.py to create executable
    subprocess.call(['python3', 'setup.py', 'build'])

    # Read the current version
    if __version__ is None:
        exit('Cannot find version in file: {}'.format(VERSION_FILE))

    changelog = _get_changelog(__version__)
    # Explain architecture= amd64
    # The architecture is AMD64-compatible and Debian AMD64 will run on AMD and
    # Intel processors with 64-bit support.
    # Because of the technology paternity, Debian uses the name "AMD64".

    config = dict(
        version=__version__,
        name='Jeroen van der Heijden',
        email='jeroen@transceptor.technology',
        company='Transceptor Technology',
        company_email='info@transceptor.technology',
        datetime=datetime.datetime.utcnow().strftime(
                '%a, %d %b %Y %H:%M:%S') + ' +0000',
        architecture={
            '32bit': 'i386',
            '64bit': 'amd64'}[platform.architecture()[0]],
        archother={
            '32bit': 'i386',
            '64bit': 'x86_64'}[platform.architecture()[0]],
        homepage='http://siridb.net',
        distribution=_get_distribution(),
        curdate=datetime.datetime.utcnow().strftime('%d %b %Y'),
        year=datetime.datetime.utcnow().year,
        package='siridb-manage',
        description='SiriDB Manage Tool',
        long_description='''
 Tool for creating and extending SiriDB time series databases.
        '''.rstrip(),
        explain='create and extend a SiriDB time series database',
        depends='${shlibs:Depends}, '
                '${misc:Depends}',
        changelog=changelog.strip()
    )

    OVERRIDES = open(
        'deb/OVERRIDES', 'r').read().strip().format(**config)
    CHANGELOG = open(
        'deb/CHANGELOG', 'r').read().strip().format(**config)
    CONTROL = open(
        'deb/CONTROL', 'r').read().strip().format(**config)
    MANPAGE = open(
        'deb/MANPAGE', 'r').read().strip().format(**config)
    COPYRIGHT = open(
        'deb/COPYRIGHT', 'r').read().strip().format(**config)
    RULES = open(
        'deb/RULES', 'r').read().strip()

    temp_path = os.path.join('build', 'temp')
    if os.path.isdir(temp_path):
        shutil.rmtree(temp_path)

    source_path = os.path.join('build', __version__)
    if not os.path.isdir(source_path):
        sys.exit('ERROR: Cannot find path: {}'.format(source_path))

    deb_file = '{package}_{version}_{architecture}.deb'.format(**config)
    source_deb = os.path.join(temp_path, deb_file)
    dest_deb = os.path.join('build', deb_file)

    if os.path.exists(dest_deb):
        os.unlink(dest_deb)

    pkg_path = os.path.join(temp_path, '{}-{}'.format(config['package'],
                                                      config['version']))
    debian_path = os.path.join(pkg_path, 'debian')

    pkg_src_path = os.path.join(pkg_path, 'src')

    debian_source_path = os.path.join(debian_path, 'source')

    target_path = os.path.join(pkg_src_path, 'usr', 'lib', 'siridb', 'manage')

    os.makedirs(debian_source_path)
    shutil.copytree(source_path, target_path)

    with open(os.path.join(debian_path, 'source', 'format'), 'w') as f:
        f.write('3.0 (quilt)')

    with open(os.path.join(debian_path, 'compat'), 'w') as f:
        f.write('9')

    changelog_file = 'ChangeLog'

    if os.path.isfile(changelog_file):
        with open(changelog_file, 'r') as f:
            current_changelog = f.read()
    else:
        current_changelog = ''

    if '{package} ({version})'.format(**config) not in current_changelog:
        changelog = CHANGELOG + '\n\n' + current_changelog

        with open(changelog_file, 'w') as f:
            f.write(changelog)

    shutil.copy(changelog_file, os.path.join(debian_path, 'changelog'))

    with open(os.path.join(debian_path, 'control'), 'w') as f:
        f.write(CONTROL)

    with open(os.path.join(debian_path, 'copyright'), 'w') as f:
        f.write(COPYRIGHT)

    rules_file = os.path.join(debian_path, 'rules')
    with open(rules_file, 'w') as f:
        f.write(RULES)

    os.chmod(rules_file, os.stat(rules_file).st_mode | stat.S_IEXEC)

    with open(os.path.join(debian_path, 'links'), 'w') as f:
        f.write('/usr/lib/siridb/manage/{package} /usr/sbin/{package}\n'.format(
            **config))

    with open(os.path.join(debian_path, 'install'), 'w') as f:
        f.write('''src/usr /''')

    with open(os.path.join(debian_path, '{}.1'.format(
            config['package'])), 'w') as f:
        f.write(MANPAGE)

    with open(os.path.join(debian_path, '{}.manpages'.format(
            config['package'])), 'w') as f:
        f.write('debian/{}.1'.format(config['package']))

    with open(os.path.join(debian_path, '{}.lintian-overrides'.format(
            config['package'])), 'w') as f:
        f.write(OVERRIDES)

    subprocess.call(['debuild', '-us', '-uc', '-b'], cwd=pkg_path)

    if os.path.exists(source_deb):
        shutil.move(source_deb, dest_deb)
        shutil.rmtree(temp_path)
        sys.exit('Successful created package: {}'.format(dest_deb))
    else:
        sys.exit('ERROR: {} not created'.format(source_deb))
