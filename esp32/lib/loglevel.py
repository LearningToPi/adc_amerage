DEBUG = 7
INFO = 6
NOTICE = 5
WARNING = 4
ERROR = 3
CRITICAL = 2
ALERT = 1
EMERGENCY = 0
EMERG = 0

log_level_strings = ['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG']

def log_str(level:int):
    """ Return a string matching the level number """
    if 0 <= level <= 7:
        return log_level_strings[level]
    return 'OUT-OF-RANGE'
