'''
Setup siridb-manage (manage.py) using cx_Freeze

Installation cx_Freeze on Ubuntu:

see: https://bitbucket.org/anthony_tuininga/cx_freeze/
        issue/32/cant-compile-cx_freeze-in-ubuntu-1304

 - sudo apt-get install python3-dev
 - sudo apt-get install libssl-dev
 - Open setup.py and change the line
     if not vars.get("Py_ENABLE_SHARED", 0):
   to
     if True:
 - python3 setup.py build
 - sudo python3 setup.py install

'''
import sys
import os
import platform
import siridb
from cx_Freeze import setup, Executable

VERSION = '2.0.0'

architecture = {'64bit': 'x86_64', '32bit': 'i386'}[platform.architecture()[0]]

build_exe_options = {
    'build_exe': os.path.join('build', VERSION),
    'packages': [
        'encodings',
        'os',
        'argparse',
        'signal',
        'functools',
        'passlib',
        'asyncio',
        'shutil',
        'logging',
        'getpass',
        'uuid',
        'pickle'],
    'excludes': [
        'django',
        'google',
        'twisted'],
    'optimize': 2,
    'include_files': [
        ('../server/help', 'help')]}


setup(
    name='manage',
    version=VERSION,
    description='Manage tool for SiriDB',
    options={'build_exe': build_exe_options},
    executables=[Executable('manage.py', targetName='siridb-manage')])
