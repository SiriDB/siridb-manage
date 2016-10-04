import re

DURATIONS = {
    '1h': [3600, '1 hour'],
    '2h': [7200, '2 hours'],
    '6h': [21600, '26hours'],
    '12h': [43200, '12 hours'],
    '1d': [86400, '1 day'],
    '2d': [172800, '2 days'],
    '4d': [345600, '4 days'],
    '1w': [604800, '1 week'],
    '10d': [864000, '10 days'],
    '2w': [1209600, '2 weeks'],
    '4w': [2419200, '4 weeks']}



DBPROPS = [
    'timezone',
    'time_precision',
    'duration_log',
    'duration_num',
    'dbname',
    'drop_threshold']

DEFAULT_CLIENT_PORT = 9000
DEFAULT_BACKEND_PORT = 9010
DEFAULT_DB_PATH = '/var/lib/siridb/'
DEFAULT_CONFIG_FILE = '/etc/siridb/siridb.conf'
DEFAULT_TIMEZONE = 'NAIVE'
DEFAULT_BUFFER_SIZE = 1024
MAX_BUFFER_SIZE = 10485760  # 10MB (655295 points)
DEFAULT_DROP_THRESHOLD = 1.0

# Database name:
#    - minimum 2, maximum 20 chars
#    - starting with an alphabetic char
#    - middle can be hyphen or number or alphabetic chars
#    - ending with number or alphabetic char
DBNAME_VALID_NAME = re.compile('^[a-zA-Z][a-zA-Z0-9-_]{,18}[a-zA-Z0-9]$')

DEFAULT_CONFIG = '''
# Welcome to the SiriDB options file
#
# Network access can be controlled with query commands. By default only
# localhost has access to the database.
# You might want to add another network/IP and you can do this with the
# following command:
#
#    curl -X POST -d 'q=grant full to network "192.168.10.0/24"' \
#        -d 'd=my_database' -d 'u=siri' -d 'p=iris' \
#        'http://localhost:port/query'
#
# Note: the user name and password used above are the defaults, maybe you have
#       changed them...
#

[buffer]
# Path used to save the buffer files.
# In case you later plan to change this location you have to manually move the
# buffer file to the new location.
path = {buffer_path}

'''