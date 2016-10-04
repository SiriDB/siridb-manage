'''Settings class.

This are SiriDB settings which are applicable for all databases running
on this server.

:copyright: 2015, Jeroen van der Heijden (Transceptor Technology)
'''

import os
import logging
import socket
import configparser
from constants import DEFAULT_BACKEND_PORT
from constants import DEFAULT_DB_PATH
from constants import DEFAULT_CONFIG_FILE

__ADDRESS_ERROR_MSG = '''
ERROR: we need an address and port which can be used to connect to!

Syntax: address:port

Address:
    Can be a host-name like 'localhost', a FQDN like 'server.local',
    an IPv4 address like '192.168.1.1' or IPv6 address like '1302:6::1'.

    For 'listen_http' and 'listen_client' it's also allowed to use
    a wild-card '*'.

Port:
    Any number between 1 and 65536

Got value: {!r}

Please verify the value in {!r}
'''

# configparser is set to global so we do not need cleanup after reading config.
config = configparser.RawConfigParser()
config.optionxform = str  # Enable a case sensitive configuration file


class _SuppressHelper:
    '''Helper class used to ignore error while reading with configparser.'''
    def __init__(self):
        self._exceptions = \
            configparser.NoOptionError, configparser.NoSectionError
        self._critical = ValueError

    def __enter__(self):
        pass

    def __exit__(self, exctype, excinst, exctb):
        if exctype is not None and issubclass(exctype, self._exceptions):
            logging.warning('{}, using default value...'.format(excinst))
            return True
        if exctype is not None and issubclass(exctype, self._critical):
            import sys
            logging.critical(str(excinst))
            sys.exit(1)
        return False


class Settings:

    def __init__(self):
        '''Initialize with default values.'''
        self.listen_client_address = \
            self.listen_backend_address = \
            socket.getfqdn()
        # note: we do not user the default HTTP and client port here since
        # the default is to disable those
        self.listen_backend_port = DEFAULT_BACKEND_PORT
        self.default_db_path = DEFAULT_DB_PATH
        self.databases = {}
        self.config_file = DEFAULT_CONFIG_FILE

    def _check_db_dir(self, dn):
        '''Returns True if the given directory is a SiriDB database directory.
        '''
        if dn.startswith('__'):
            # skip folders starting with double underscore
            return False
        dn = os.path.join(self.default_db_path, dn)
        if not os.path.isdir(dn):
            return False
        if not os.path.isfile(os.path.join(dn, 'database.conf')):
            return False
        if not os.path.isfile(os.path.join(dn, 'database.dat')):
            return False
        return True

    @staticmethod
    def _get_address(addr, fn, wildcard=True):
        try:
            address, port = \
                addr[:addr.rfind(':')], int(addr[addr.rfind(':') + 1:])
        except ValueError:
            raise ValueError(__ADDRESS_ERROR_MSG.format(addr, fn))
        if not 1 < port < 2 ** 16:
            raise ValueError(__ADDRESS_ERROR_MSG.format(addr, fn))

        if wildcard and address == '*':
            return address, port

        try:
            if address.startswith('[') and address.endswith(']'):
                address = address.lstrip('[').rstrip(']')
                socket.inet_pton(socket.AF_INET6, address)
            else:
                socket.inet_pton(socket.AF_INET, address)
        except socket.error:
            try:
                socket.gethostbyname(address)
            except socket.error:
                raise ValueError(__ADDRESS_ERROR_MSG.format(addr, fn))
        return address, port

    def read_config(self):
        '''Read settings from global configuration file.'''
        global config
        fn = self.config_file
        with open(fn, 'r', encoding='utf-8') as f:
            config.read_file(f)
        with _SuppressHelper():
            self.listen_client_address, self.listen_client_port = \
                self._get_address(
                    config.get('siridb', 'listen_client'), fn, wildcard=True)
        with _SuppressHelper():
            self.listen_backend_address, self.listen_backend_port = \
                self._get_address(
                    config.get('siridb', 'listen_backend'), fn, wildcard=False)
        with _SuppressHelper():
            self.default_db_path = \
                config.get('siridb', 'default_db_path')

        if os.path.isdir(self.default_db_path):
            for dbname in [dn
                           for dn in os.listdir(self.default_db_path)
                           if self._check_db_dir(dn)]:
                self.databases[dbname] = \
                    os.path.join(self.default_db_path, dbname)

        # this can be used to add databases at another location
        # than the DB_PATH
        if 'databases' in config:
            for dbname in config['databases']:
                self.databases[dbname] = config.get('databases', dbname)
