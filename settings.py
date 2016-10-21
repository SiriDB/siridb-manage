'''Settings class.

This are SiriDB settings which are applicable for all databases running
on this server.

:copyright: 2015, Jeroen van der Heijden (Transceptor Technology)
'''

import os
import logging
import socket
import configparser
from constants import DEFAULT_CONFIG_FILE

# configparser is set to global so we do not need cleanup after reading config.
config = configparser.RawConfigParser()
config.optionxform = str  # Enable a case sensitive configuration file

IP_SUPPORT_MAP = {
    'ALL' : '127.0.0.1',
    'IPV4ONLY': '127.0.0.1',
    'IPV6ONLY': '::1'
}

class Settings:

    def __init__(self):
        self.config_file = DEFAULT_CONFIG_FILE

    @staticmethod
    def _get_address(addr, fn):
        addr = addr.replace('%HOSTNAME', socket.gethostname())
        try:
            address, port = \
                addr[:addr.rfind(':')], int(addr[addr.rfind(':') + 1:])
        except ValueError:
            raise ValueError(__ADDRESS_ERROR_MSG.format(addr, fn))
        if not 1 < port < 2 ** 16:
            raise ValueError(__ADDRESS_ERROR_MSG.format(addr, fn))

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

        self.listen_client_port = config.getint('siridb', 'listen_client_port')
        self.server_address, self.listen_backend_port = \
            self._get_address(config.get('siridb', 'server_name'), fn)

        self.default_db_path = config.get('siridb', 'default_db_path')

        ip_support = config.get('siridb', 'ip_support')
        if ip_support not in IP_SUPPORT_MAP:
            ip_support = 'ALL'

        self.localhost = IP_SUPPORT_MAP[ip_support]

