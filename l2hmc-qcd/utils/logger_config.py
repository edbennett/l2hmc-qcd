"""
logger_config.py
"""
from __future__ import absolute_import, division, print_function, annotations
import warnings
#  warnings.filterwarnings('once')
#  warnings.simplefilter('once')
import os
import sys
import logging
from pathlib import Path
from rich.logging import RichHandler
from rich.console import Console as RichConsole
from rich.theme import Theme
from tensorflow.python.keras.utils.generic_utils import CustomMaskWarning

import logging.config
#  from utils.logger import Logger

REPO = 'l2hmc-qcd'

# Directories
#BASE_DIR = Path(__file__).parent.parent.absolute()
BASE_DIR = Path(str(os.getcwd()))
CONFIG_DIR = Path(BASE_DIR, 'config')
LOGS_DIR = Path(BASE_DIR, 'l2hmclogs')
DATA_DIR = Path(BASE_DIR, 'data')
MODEL_DIR = Path(BASE_DIR, 'model')
STORES_DIR = Path(BASE_DIR, 'stores')

# Local stores
BLOB_STORE = Path(STORES_DIR, 'blob')
FEATURE_STORE = Path(STORES_DIR, 'feature')
MODEL_REGISTRY = Path(STORES_DIR, 'model')

# Create dirs
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR.mkdir(parents=True, exist_ok=True)
STORES_DIR.mkdir(parents=True, exist_ok=True)
BLOB_STORE.mkdir(parents=True, exist_ok=True)
FEATURE_STORE.mkdir(parents=True, exist_ok=True)
MODEL_REGISTRY.mkdir(parents=True, exist_ok=True)


# Logger
logging_config = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "minimal": {"format": "%(message)s"},
        "detailed": {
            "format": "%(levelname)s %(asctime)s [%(filename)s:%(funcName)s:%(lineno)d]\n%(message)s\n"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "minimal",
            "level": logging.DEBUG,
        },
        "info": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Path(LOGS_DIR, "info.log"),
            "maxBytes": 10485760,  # 1 MB
            "backupCount": 10,
            "formatter": "detailed",
            "level": logging.INFO,
        },
        "error": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": Path(LOGS_DIR, "error.log"),
            "maxBytes": 10485760,  # 1 MB
            "backupCount": 10,
            "formatter": "detailed",
            "level": logging.ERROR,
        },
    },
    "loggers": {
        "root": {
            "handlers": ["console", "info", "error"],
            "level": logging.DEBUG,
            "propagate": False,
        },
    },
}


def in_notebook():
    """Check if we're currently in a jupyter notebook."""
    try:
        # pylint:disable=import-outside-toplevel
        from IPython import get_ipython
        try:
            if 'IPKernelApp' not in get_ipython().config:
                return False
        except AttributeError:
            return False
    except ImportError:
        return False
    return True


theme = {}
if in_notebook():
    theme = {
        'repr.number': 'bold #87ff00',
        'repr.attrib_name': 'bold #ff5fff',
        'repr.str': 'italic #FFFF00',
    }


with_jupyter = in_notebook()
#  console = RichConsole(record=False, log_path=False,
#                        force_jupyter=with_jupyter,
#                        force_terminal=(not with_jupyter),
#                        log_time_format='[%x %X] ',
#                        theme=Theme(theme))#, width=width)
logging.config.dictConfig(logging_config)
logger = logging.getLogger('root')
logger.handlers[0] = RichHandler(markup=True,
                                 rich_tracebacks=True,
                                 #  console=console,
                                 show_path=False)

#  tflogger = logging.getLogger('tensorflow')
#  tflogger.handlers[0] = RichHandler(markup=True,
#                                     rich_tracebacks=True,
#                                     show_path=False)

logging.captureWarnings(True)
#  warnings.filterwarnings('once', 'seaborn')
#  warnings.filterwarnings('once', 'keras')
#  warnings.filterwarnings('once', 'UserWarning:')
#  warnings.filterwarnings('once', 'CustomMaskWarning:')
logging.getLogger('matplotlib').setLevel(logging.CRITICAL)
logging.getLogger('seaborn').setLevel(logging.CRITICAL)
logging.getLogger('seaborn.axisgrid').setLevel(logging.CRITICAL)
logging.getLogger('keras').setLevel(logging.CRITICAL)
logging.getLogger('arviz').setLevel(logging.CRITICAL)
logging.getLogger('tensorflow').setLevel(logging.CRITICAL)
logging.getLogger('tensorflow.keras').setLevel(logging.CRITICAL)
logging.getLogger('tensorflow.python.keras.utils.generic_utils').setLevel(logging.CRITICAL)
warnings.simplefilter('once', category=CustomMaskWarning, lineno=494)
warnings.filterwarnings('once',
                        module='tensorflow.python.keras.utils.generic_utils',
                        category=CustomMaskWarning, lineno=494, append=True)
#  logging.getLogger('tensorflow').setLevel(logging.ERROR)
                                 #  console=Logger().console)

# Exclusion criteria
EXCLUDED_TAGS = []