#!/usr/bin/python3 -OO
import sys
import os
import argparse
import signal
import functools
import asyncio
import shutil
import logging
import getpass
import uuid
import pickle
import qpack
import time
from settings import Settings
from constants import DEFAULT_TIMEZONE
from constants import DEFAULT_DROP_THRESHOLD
from constants import DEFAULT_BUFFER_SIZE
from constants import DURATIONS
from constants import DBNAME_VALID_NAME
from constants import MAX_BUFFER_SIZE
from constants import DEFAULT_CONFIG
from constants import DEFAULT_CLIENT_PORT
from constants import DBPROPS
from constants import MAX_NUMBER_DB
from version import __version__
from version import __version_info__
from version import __email__
from version import __maintainer__
from siridb.connector import connect
from siridb.connector import SiriDBProtocol
from siridb.connector import async_server_info
from siridb.connector.lib.protomap import CPROTO_REQ_LOADDB
from siridb.connector.lib.exceptions import ServerError
from siridb.connector.lib.exceptions import PoolError
from siridb.connector.lib.exceptions import UserAuthError
from siridb.connector.lib.exceptions import AuthenticationError

settings = Settings()
PROMPT = '> '
FULL_AUTH = 'full'
siri = None
local_siridb_info = None
remote_siridb_info = None

def check_valid_dbname(dbname):
    if not isinstance(dbname, str):
        raise ValueError(
            'Need a string value for dbname, got {}'.format(
                type(dbname).__name__))
    if not DBNAME_VALID_NAME.match(dbname):
        raise ValueError(
            'Database name should be 2 to 20 characters, stating with an '
            'alphabetic and ending with an alphabetic or number character. '
            'In the middle hyphens are allowed.')


def mk_path(path):
    if not os.path.exists(path):
        os.makedirs(path)
    elif os.listdir(path):
        raise OSError('path is not empty: {}'.format(path))


def create_database(
        dbname,
        dbpath,
        time_precision='ms',
        duration_log='1d',
        duration_num='1w',
        timezone=DEFAULT_TIMEZONE,
        drop_threshold=DEFAULT_DROP_THRESHOLD,
        buffer_size=DEFAULT_BUFFER_SIZE,
        config={},
        _uuid=None,
        _pool=0):
    '''
    Note: duration_log and duration_num can both be integer or string.
          get_duration() understands both.
    '''
    check_valid_dbname(dbname)

    _config = {
        'buffer_path': dbpath
    }
    _config.update(config)

    if time_precision not in ['s', 'ms', 'us', 'ns']:
        raise ValueError('time_precision must be either \'s\' (seconds), '
                         '\'ms\' (milliseconds), \'us\' (microseconds) '
                         'or \'ns\' (nanoseconds) but received {!r}'
                         .format(time_precision))

    time_precision = get_time_precision(time_precision)

    duration_num = get_duration(time_precision, duration_num)
    duration_log = get_duration(time_precision, duration_log)

    if _uuid is None:
        _uuid = uuid.uuid1()

    with open(os.path.join(dbpath, 'database.conf'),
              'w',
              encoding='utf-8') as f:
        f.write(DEFAULT_CONFIG.format(**_config))

    db_obj = [
        1,                                          # shema version
        _uuid.bytes,                                # uuid
        dbname,                                     # dbname
        time_precision,                             # time precision
        buffer_size,                                # buffer size
        duration_num,                               # duration num
        duration_log,                               # duration log
        timezone,                                   # timezone
        drop_threshold,                             # drop threshold
    ]

    with open(os.path.join(dbpath, 'database.dat'), 'wb') as f:
        f.write(qpack.packb(db_obj))


def color_red(s):
    return '\x1b[31m{}\x1b[0m'.format(s)


def color_yellow(s):
    return '\x1b[33m{}\x1b[0m'.format(s)


def color_purple(s):
    return '\033[95m{}\x1b[0m'.format(s)


def color_blue(s):
    return '\033[94m{}\x1b[0m'.format(s)


def print_header(title, desciption, has_default):
    print('\n',
          color_blue(title),
          '(enter to use default)' if has_default else '')
    if desciption:
        print(desciption)


def print_error(s):
    print('\n', color_yellow(s), '\n')


def print_action(action):
    print(' {}'.format(color_yellow(action)))


def get_input(default):
    return input('[{}] {}'.format(color_red(default), PROMPT)
                 if default is not None
                 else PROMPT).strip()


def get_pass(default):
    return getpass.getpass('[{}] {}'.format(color_red(default), PROMPT)
                           if default is not None
                           else PROMPT).strip()


class Options:

    def __init__(self, options):
        self.options = options

    def get_options(self):
        return [option['option'] for option in self.options]

    def options_as_text(self):
        return ' or '.join([s
                            for s in [
                                ', '.join(self.get_options()[:-1]),
                                self.get_options()[-1]] if s])

    def __getitem__(self, key):
        return self.options[key]


def not_empty(s):
    if not s:
        raise ValueError('Empty value is not allowed')


def quit_manage(exit_code=0, msg='Exit manage SiriDB... bye!'):
    if siri:
        logging.debug('Close siridb connection')
        siri.close()

    if exit_code:
        logging.error(msg)
    else:
        logging.info(msg)

    sys.exit(exit_code)


def menu(title, options, description='', default=None):
    print_header(title, description, default is not None)
    while True:
        for option in options:
            print(' [{}] - {}'.format(color_red(option['option']),
                                      option['text']))

        inp = get_input(default)
        if not inp:
            inp = default

        if inp not in options.get_options():
            print('\nInvalid option: {}, options are: {}'.format(
                color_red(inp), options.options_as_text()))
        else:
            return inp


def ask_string(title,
               description='',
               default=None,
               func=lambda x: None,
               is_password=False):
    print_header(title, description, default is not None)
    while True:
        inp = get_pass(default) if is_password else get_input(default)
        if not inp:
            inp = default
        try:
            func(inp)
        except Exception as e:
            print('\n', e)
        else:
            return inp


def ask_int(title, description='', default=None, func=lambda x: None):
    print_header(title, description, default is not None)
    while True:
        inp = get_input(default)
        if not inp:
            inp = default
        try:
            inp = int(inp)
        except ValueError:
            print('\nExpecting an integer value but got {!r}'.format(inp))
        else:
            try:
                func(inp)
            except Exception as e:
                print('\n', e)
            else:
                return inp


def check_valid_buffer_size(i):
    if i % 512 != 0:
        raise ValueError('Please use a multiple of 512 as a buffer size, '
                         'got {}'.format(i))
    check_min_max(i, 512, MAX_BUFFER_SIZE)


def check_min_max(i, mi, ma, s='a value'):
    if i < mi or i > ma:
        raise ValueError('Expecting {} between {} and {} but got {}'.format(
            s, mi, ma, i))


class SiriDBInfo():
    def __init__(self, version, dblist):
        self.version = version
        self.dblist = dblist


async def set_local_siridb_info(host, port):
    global local_siridb_info
    try:
        result = await async_server_info(host, port)
    except Exception as e:
        logging.error('Connection error: {}'.format(e))
        sys.exit(1)
    else:
        if result:
            local_siridb_info = SiriDBInfo(*result)


async def set_remote_siridb_info(host, port):
    global remote_siridb_info
    try:
        result = await async_server_info(host, port)
    except:
        result = None

    if result:
        remote_siridb_info = SiriDBInfo(*result)

    if remote_siridb_info is None:
        raise RuntimeError(
            'Error retreiving SiriDB info from {}:{}'.format(host, port))

    if not remote_siridb_info.dblist:
        raise RuntimeError('No databases found in {}:{}'.format(host, port))

    if local_siridb_info.version != remote_siridb_info.version:
        raise RuntimeError(
            'Local version ({}) not equal to remote version ({})'
            .format(local_siridb_info.version, remote_siridb_info.version))


def check_dbname(s):
    check_valid_dbname(s)
    if s in local_siridb_info.dblist:
        raise ValueError('Database {!r} already exists'.format(s))
    if len(local_siridb_info.dblist) >= MAX_NUMBER_DB:
        raise ValueError(
            'Cannot create {!r} because the maximum number of '
            'databases is reached. (max={})'.format(s, MAX_NUMBER_DB))


def check_loaded(dbname):
    asyncio.get_event_loop().run_until_complete(set_local_siridb_info(
        settings.localhost,
        settings.listen_client_port))
    if dbname not in local_siridb_info.dblist:
        raise ValueError('Database {!r} is not loaded, please check the '
                         'SiriDB logging to see what went wrong. (possible '
                         'cause:  SiriDB has no access to the database '
                         'folder)'.format(dbname))


class SiriDBLoadProtocol(SiriDBProtocol):

    def connection_made(self, transport):

        def finished(future):
            pass

        self.transport = transport
        self.remote_ip, self.port = transport.get_extra_info('peername')[:2]

        self.future = self.send_package(CPROTO_REQ_LOADDB,
                                        data=self._dbname,
                                        timeout=10)
        self.future.add_done_callback(finished)


async def load_database(dbpath, host, port):
    if dbpath[-1] != '/':
        dbpath += '/'

    loop = asyncio.get_event_loop()

    client = loop.create_connection(
        lambda: SiriDBLoadProtocol(None, None, dbpath),
        host=host,
        port=port)

    transport, protocol = await asyncio.wait_for(client, timeout=10)

    await protocol.future
    transport.close()


def connect_other(dbname, host, port, username, password):
    global siri
    siri = connect(username, password, dbname, host, port)


def connect_to_siridb(dbname, address, port, username, password):
    try:
        connect_other(dbname, address, port, username, password)
    except Exception as e:
        raise ConnectionError('Error while connecting: {}'.format(e))

    try:
        result = siri.query('show version')
    except QueryError:
        raise ConnectionError('User {!r} has no {!r} privileges'.format(
            username, FULL_AUTH))

    version = result['data'][0]['value']

    if tuple(map(int, version.split('.')))[:2] != __version_info__[:2]:
        raise ValueError('SiriDB Server is running version {}, '
                         'we are using  {}'.format(version, __version__))

    result = siri.query('list users name, access')

    for user in result['users']:
        if user[0] == username and user[1] != FULL_AUTH:
            raise ConnectionError('User {!r} has no {!r} privileges'.format(
                username, FULL_AUTH))


def join_database():
    other_address = None
    other_port = DEFAULT_CLIENT_PORT
    username = None
    dbname = None
    while True:
        other_address = ask_string(
            title='Remote host or IP-address',
            default=other_address,
            func=not_empty,
            description='If your database has already more than one server '
            'you can just choose one')

        other_port = ask_int(
            title='Remote client port',
            default=other_port,
            func=functools.partial(check_min_max, mi=1, ma=65535))

        try:
            asyncio.get_event_loop().run_until_complete(set_remote_siridb_info(
                other_address,
                other_port))
        except Exception as e:
            print_error(e)
            continue

        db = menu(
            title='Database',
            options=Options([{'option': str(i), 'text': s} for i, s in enumerate(remote_siridb_info.dblist)]),
            default='0')
        dbname = remote_siridb_info.dblist[int(db)]

        if dbname in local_siridb_info.dblist:
            print_error('Database "{}" already exist on this server'.format(
                dbname))
            continue

        username = ask_string(
            title='User name',
            default=username,
            func=not_empty,
            description='The given user name should have {!r} '
            'privileges'.format(FULL_AUTH))

        password = ask_string(
            title='Password',
            is_password=True)

        try:
            connect_to_siridb(dbname,
                              other_address,
                              other_port,
                              username,
                              password)
        except Exception as e:
            print_error(e)
        else:
            break

        print_action('Please verify your input and try again...')

    dbpath = os.path.join(settings.default_db_path, dbname)
    mk_path(dbpath)
    buffer_path = ask_buffer_path(dbpath)

    while True:
        try:
            result = siri.query('list pools pool, servers, series ')
        except QueryError as e:
            print_error(e)
            answer = menu(
                title='Do you want to retry?',
                options=Options([
                    {'option': 'r', 'text': 'Retry'},
                    {'option': 'q', 'text': 'Quit'}]),
                default='r')

            if answer == 'r':
                continue

            quit_manage(1, e)
        break

    pools = sorted(result['pools'], key=lambda t: t[0])

    pool_or_replica(pools, dbpath, buffer_path)


def show_pool_status(pools):
    print(color_blue('{}{}{}'.format('pool'.ljust(10),
                                     'servers'.ljust(10),
                                     'series')))

    for pool in pools:
        print('{}{}{}'.format(str(pool[0]).ljust(10),
                              str(pool[1]).ljust(10),
                              str(pool[2])))


def create_joined_database(dbpath, buffer_path, pool, new_pool, action_str):
    dbconfig = siri.query('show {}'.format(','.join(DBPROPS)))
    props = {prop['name']: prop['value'] for prop in dbconfig['data']}
    cfg = {}

    ask_buffer_size(cfg)

    cfg['buffer_path'] = buffer_path

    dbname = props['dbname']

    answer = menu(
        title='Are you sure you want to continue and {}?'.format(action_str),
        options=Options([
            {'option': 'y', 'text': 'Yes, I\'m sure'},
            {'option': 'n', 'text': 'No, go back'}]),
        default='n')
    if answer == 'n':
        return None

    create_and_register_server(dbname,
                               dbpath,
                               pool,
                               props,
                               cfg,
                               new_pool,
                               allow_retry=True)

def get_time_precision(s):
    _map = ['s', 'ms', 'us', 'ns']
    return _map.index(s)


def get_duration(tp, duration):
    return duration if isinstance(duration, int) else DURATIONS[duration][0] * (1000**tp)


def create_and_register_server(dbname,
                               dbpath,
                               pool,
                               props,
                               cfg,
                               new_pool,
                               allow_retry=True):
    def rollback(*args):
        logging.warning('Roll-back create database...')
        shutil.rmtree(dbpath)
        quit_manage(*args)

    address = settings.server_address
    port = settings.listen_backend_port
    _uuid = uuid.uuid1()

    create_database(
        dbname=dbname,
        dbpath=dbpath,
        time_precision=props['time_precision'],
        duration_log=props['duration_log'],
        duration_num=props['duration_num'],
        timezone=props['timezone'],
        drop_threshold=props['drop_threshold'],
        config=cfg,
        _uuid=_uuid,
        _pool=pool)
    logging.info('Added database {!r}'.format(props['dbname']))

    for fn in ('servers.dat',
               'users.dat',
               'groups.dat'):
        try:
            content = siri._get_file(fn)
        except ServerError as e:
            rollback(1, e)

        with open(os.path.join(dbpath, fn), 'wb') as f:
            f.write(content)

    if new_pool:
        with open(os.path.join(dbpath, '.reindex'), 'wb') as f:
            pass

    with open(os.path.join(dbpath, 'servers.dat'), 'rb') as f:
        qp_servers = f.read()
        servers_obj = qpack.unpackb(qp_servers)

    server = [_uuid.bytes, bytes(address, 'utf-8'), port, pool]
    servers_obj.append(server)

    with open(os.path.join(dbpath, 'servers.dat'), 'wb') as f:
        qp_servers = qpack.packb(servers_obj)
        f.write(qp_servers)

    result = siri.query('list servers name, status')

    expected = 'running'
    for srv in result['servers']:
        if srv[1] != expected:
            rollback(
                1,
                'All servers must have status {!r} '
                'before we can continue. As least {!r} has status {!r}'
                .format(expected, srv[0], srv[1]));

    asyncio.get_event_loop().run_until_complete(load_database(
        dbpath,
        settings.localhost,
        settings.listen_client_port))

    time.sleep(1)

    try:
        check_loaded(dbname)
    except Exception as e:
        rollback(1, e)
    else:
        logging.info(
            'Database loaded... now register the server'.format(dbname))

    while True:
        try:
            siri._register_server(server)
        except Exception as e:
            if allow_retry:
                print_error(e)
                answer = menu(
                    title='Do you want to retry the registration?',
                    options=Options([
                        {'option': 'r', 'text': 'Retry'},
                        {'option': 'q', 'text': 'Quit'}]),
                    default='r')
                if answer == 'r':
                    continue
                rollback(0, None)
            else:
                rollback(1, e)
        break

    quit_manage(0, 'Finished joining database {!r}...'.format(dbname))


def create_new_pool(pools, dbpath, buffer_path):
    pool = len(pools)
    create_joined_database(dbpath,
                           buffer_path,
                           pool,
                           True,
                           'create a new pool: {}'.format(pool))


def create_new_replica(pools, dbpath, buffer_path):
    opts = [{
        'option': str(pool[0]),
        'text': 'Pool ID {}'.format(pool[0])
    } for pool in pools if pool[1] == 1]

    pool = menu(
        title='For which pool do you want to create a replica?',
        description=None
        if opts
        else '(All available pools already have a replica)',
        options=Options(opts + [{'option': 'b', 'text': 'Back'}])
    )
    if pool == 'b':
        return None
    pool = int(pool)

    create_joined_database(dbpath,
                           buffer_path,
                           pool,
                           False,
                           'create a replica for pool {}'.format(pool))


def pool_or_replica(pools, dbpath, buffer_path):
    while True:
        action = menu(
            title='New pool or extend and existing pool (replica)?',
            options=Options([
                {'option': 'p',
                 'text': 'Create a new pool'},
                {'option': 'r',
                 'text': 'Create a replica for an existing pool'},
                {'option': 's',
                 'text': 'Show current pools'},
                {'option': 'q',
                 'text': 'quit'}]))
        {
            'q': quit_manage,
            'p': lambda: create_new_pool(pools, dbpath, buffer_path),
            'r': lambda: create_new_replica(pools, dbpath, buffer_path),
            's': lambda: show_pool_status(pools)
        }[action]()


def ask_buffer_path(dbpath):
    return ask_string(
        title='Location to store the buffer file',
        description='It can be useful to store the buffer file on a separate '
        '(fast) disk, for example a Solid State Drive (SSD).'.format(
            args.config),
        default=dbpath,
        func=mk_path)


def ask_buffer_size(cfg):
    cfg['buffer_size'] = ask_int(
        title='Buffer size',
        default=DEFAULT_BUFFER_SIZE,
        func=check_valid_buffer_size)


def _arg_dbname(parser):
    parser.add_argument(
        '--dbname',
        type=str,
        required=True,
        help='Database name.')


def _arg_buffer_path(parser):
    parser.add_argument(
        '--buffer-path',
        type=str,
        default=None,
        help='Alternative location for storing the buffer file.')


def _arg_time_precision(parser):
    parser.add_argument(
        '--time-precision',
        type=str,
        choices=['s', 'ms', 'us', 'ns'],
        default='ms',
        help='Time precision for the records in the database in milliseconds '
        'or seconds.')


def _arg_duration_num(parser):
    parser.add_argument(
        '--duration-num',
        type=str,
        choices=list(DURATIONS.keys()),
        default='1w',
        help='Time span used for number (float and integer) shards.')


def _arg_duration_log(parser):
    parser.add_argument(
        '--duration-log',
        type=str,
        choices=list(DURATIONS.keys()),
        default='1d',
        help='Time span used for log (string) shards .')


def _arg_buffer_size(parser):
    parser.add_argument(
        '--buffer-size',
        type=int,
        default=DEFAULT_BUFFER_SIZE,
        help='Size in bytes per series for storing points in memory. Use a '
        'multiple of 512 as a buffer size.')


def _arg_remote_address(parser):
    parser.add_argument(
        '--remote-address',
        type=str,
        required=True,
        help='Remote host or IP-address of one of the servers in the SiriDB '
        'cluster you want to join.')


def _arg_remote_port(parser):
    parser.add_argument(
        '--remote-port',
        type=int,
        default=9000,
        help='Remote port of one of the servers in the SiriDB cluster you '
        'want to join.')


def _arg_user(parser):
    parser.add_argument(
        '--user',
        type=str,
        required=True,
        help='User for connecting to the SiriDB cluster. The user should '
        'have {!r} privileges.'.format(FULL_AUTH))


def _arg_password(parser):
    parser.add_argument(
        '--password',
        type=str,
        default='',
        help='You will be prompted for a password when leaving this empty.')


def _arg_pool(parser):
    parser.add_argument(
        '--pool',
        type=int,
        required=True,
        help='Pool ID for which you want to create the replica. A pool can '
        'only have two servers so you must choose a pool with exactly one '
        'server. (use \'\' for an overview)')


def form_create_new_database():
    dbname = ask_string(
        title='Type a name for the new database',
        description='Note: this value cannot be changed after the database '
        'has been created',
        func=check_dbname)

    dbpath = os.path.join(settings.default_db_path, dbname)
    try:
        mk_path(dbpath)
    except Exception as e:
        quit_manage(1, e)

    buffer_path = ask_buffer_path(dbpath)

    time_precision = menu(
        title='Time precision',
        options=Options([
            {'option': 's', 'text': 'seconds'},
            {'option': 'ms', 'text': 'milliseconds'},
            {'option': 'us', 'text': 'microseconds'},
            {'option': 'ns', 'text': 'nanoseconds'}
        ]),
        default='ms')

    duration_options = [{'option': k, 'text': v[1]} for k, v in DURATIONS.items()]

    duration_num = menu(
        title='Number (float and integer) sharding duration',
        options=Options(duration_options),
        default='1w')

    duration_log = menu(
        title='Log (string) sharding duration',
        options=Options(duration_options),
        default='1d')

    cfg = {'buffer_path': buffer_path}

    ask_buffer_size(cfg)
    create_new_database(dbname,
                        dbpath,
                        time_precision,
                        duration_log,
                        duration_num,
                        cfg)


def create_new_database(dbname,
                        dbpath,
                        time_precision,
                        duration_log,
                        duration_num,
                        cfg):
    create_database(
        dbname=dbname,
        dbpath=dbpath,
        time_precision=time_precision,
        duration_log=duration_log,
        duration_num=duration_num,
        config=cfg)
    logging.info('Created database {!r}'.format(dbname))

    asyncio.get_event_loop().run_until_complete(load_database(
        dbpath,
        settings.localhost,
        settings.listen_client_port))

    time.sleep(1)

    try:
        check_loaded(dbname)
    except Exception as e:
        quit_manage(1, e)
    else:
        quit_manage(0, 'Database "{}" created succesfully'.format(dbname))


def main_menu():
    choice = menu(
        title='Tell me what you plan to do:',
        options=Options([
            {'option': 'c', 'text': 'create a new database'},
            {'option': 'j', 'text': 'join an existing SiriDB database'},
            {'option': 'q', 'text': 'quit'}
        ]))

    {
        'q': quit_manage,
        'j': join_database,
        'c': form_create_new_database
    }[choice]()


def signal_handler(s, f):
    quit_manage(2, '\nyou pressed ctrl+c, quiting...\n')


def parse_create_new(args):
    try:
        check_dbname(args.dbname)
        check_valid_buffer_size(args.buffer_size)
        dbpath = os.path.join(settings.default_db_path, args.dbname)
        mk_path(dbpath)

        buffer_path = args.buffer_path or dbpath
        mk_path(buffer_path)

    except Exception as e:
        quit_manage(1, e)

    cfg = {
        'buffer_path': buffer_path,
        'buffer_size': args.buffer_size,
    }
    create_new_database(args.dbname,
                        dbpath,
                        args.time_precision,
                        args.duration_log,
                        args.duration_num,
                        cfg)


def parse_create_replica_or_pool(args):
    if not args.password:
        password = ask_string(
            title='Password',
            is_password=True)
    else:
        password = args.password

    try:
        asyncio.get_event_loop().run_until_complete(set_remote_siridb_info(
                args.remote_address,
                args.remote_port))

        check_dbname(args.dbname)
        check_valid_buffer_size(args.buffer_size)

        dbpath = os.path.join(settings.default_db_path, args.dbname)
        mk_path(dbpath)

        buffer_path = args.buffer_path or dbpath
        mk_path(buffer_path)

        connect_to_siridb(args.dbname,
                          args.remote_address,
                          args.remote_port,
                          args.user,
                          password)

        result = siri.query('list pools pool, servers, series')
        if hasattr(args, 'pool'):
            pools = {pool[0]: pool[1] for pool in result['pools']}
            if args.pool not in pools:
                raise ValueError('Pool ID {} does not exists'.format(
                    args.pool))
            if pools[args.pool] != 1:
                raise ValueError('A pool can only have two servers. '
                                 'Pool ID {} already has {} servers.'
                                 .format(args.pool, pools[args.pool]))
            pool = args.pool

        else:
            pool = len(result['pools'])


        dbconfig = siri.query('show {}'.format(','.join(DBPROPS)))
    except Exception as e:
        quit_manage(1, e)

    props = {prop['name']: prop['value'] for prop in dbconfig['data']}
    cfg = {
        'buffer_path': buffer_path,
        'buffer_size': args.buffer_size,
    }

    create_and_register_server(args.dbname,
                               dbpath,
                               pool,
                               props,
                               cfg,
                               new_pool=not hasattr(args, 'pool'),
                               allow_retry=False)

if __name__ == '__main__':

    # Add ctrl+c to quit
    signal.signal(signal.SIGINT, signal_handler)

    # Read arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c',
        '--config',
        type=str,
        default='/etc/siridb/siridb.conf',
        help='path to global configuration file')
    parser.add_argument(
        '-n',
        '--noroot',
        action='store_true',
        help='allow this script to run as another user than root')
    parser.add_argument(
        '-v',
        '--version',
        action='store_true',
        help='print version information and exit')
    parser.add_argument(
        '-l', '--log-level',
        default='info',
        help='set the log level (ignored in wizard mode)',
        choices=['debug', 'info', 'warning', 'error', 'critical'])

    subparsers = parser.add_subparsers(
        dest='action',
        title='positional arguments for managing SiriDB server',
        description='Without using positional arguments we will show a '
        'interactive menu for managing SiriDB server. Use <argument> --help '
        'for more information on each argument.')

    parser_create_new = subparsers.add_parser(
        'create-new',
        help='create a new SiriDB database',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        argument_default=argparse.SUPPRESS)

    for argument in [_arg_dbname,
                     _arg_buffer_path,
                     _arg_time_precision,
                     _arg_duration_log,
                     _arg_duration_num,
                     _arg_buffer_size]:
        argument(parser_create_new)

    parser_create_replica = subparsers.add_parser(
        'create-replica',
        help='create a new replica in a SiriDB cluster',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        argument_default=argparse.SUPPRESS)

    for argument in [_arg_dbname,
                     _arg_remote_address,
                     _arg_remote_port,
                     _arg_user,
                     _arg_password,
                     _arg_pool,
                     _arg_buffer_path,
                     _arg_buffer_size]:
        argument(parser_create_replica)

    parser_create_pool = subparsers.add_parser(
        'create-pool',
        help='create a new pool in a SiriDB cluster',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        argument_default=argparse.SUPPRESS)

    for argument in [_arg_dbname,
                     _arg_remote_address,
                     _arg_remote_port,
                     _arg_user,
                     _arg_password,
                     _arg_buffer_path,
                     _arg_buffer_size]:
        argument(parser_create_pool)

    args = parser.parse_args()

    formatter = logging.Formatter(fmt='%(message)s', style='%')

    logger = logging.getLogger()
    logger.setLevel(args.log_level.upper())

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if args.version:
        quit_manage(0, '''
SiriDB Manage {version}
Maintainer: {maintainer} <{email}>
Home-page: http://siridb.net
        '''.strip().format(version=__version__,
                           maintainer=__maintainer__,
                           email=__email__))

    # Check for root
    if not args.noroot and not os.geteuid() == 0:
        quit_manage(2,
                    '\nOnly root can run this script.\n\nIf you are sure '
                    'you want to run as a user you can add the "--noroot" '
                    'argument. \nSee "{} --help" for more info.\n'
                    .format(os.path.basename(sys.argv[0])))

    # Check if global configuration file exists
    if not os.path.exists(args.config):
        quit_manage(2,
                    'Cannot find {!r}, please use --options to specify the '
                    'location for the global configuration file'
                    .format(args.config))

    # Check if we have read access to the global configuration file
    if not os.access(args.config, os.R_OK):
        quit_manage(2,
                    'Missing read access to the global configuration file: {}'
                    .format(args.config))

    # Read configuration
    settings.config_file = args.config
    settings.read_config()
    asyncio.get_event_loop().run_until_complete(set_local_siridb_info(
        settings.localhost,
        settings.listen_client_port))

    if local_siridb_info is None:
        quit_manage(2,
                    'Unable to get local SiriDB info, please check if '
                    'SiriDB is running and listening to {}:{}.'.format(
                        settings.localhost,
                        settings.listen_client_port))

    # Check if this tool and the SiriDB Server have the same version number
    if tuple(map(
            int,
            local_siridb_info.version.split('.')[:2])) != __version_info__[:2]:
        quit_manage(2,
                    'SiriDB Server (version {}) should have the same version '
                    'as this manage tool (version {})'
                    .format(local_siridb_info.version, __version__))

    if args.action is None:
        logger.setLevel('INFO')
        # Open menu
        main_menu()
    elif args.action == 'create-new':
        parse_create_new(args)
    elif args.action in ('create-replica', 'create-pool'):
        parse_create_replica_or_pool(args)
