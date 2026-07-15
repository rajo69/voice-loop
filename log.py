"""Lightweight logging: writes to console and a rotating file (logs/voiceloop.log)."""
import logging
import os
from logging.handlers import RotatingFileHandler

from common import ROOT

_LOG_DIR = os.path.join(ROOT, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_logger = logging.getLogger("voiceloop")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    fh = RotatingFileHandler(os.path.join(_LOG_DIR, "voiceloop.log"),
                             maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    _logger.addHandler(fh)
    _logger.addHandler(sh)


def info(msg):
    _logger.info(msg)


def error(msg):
    _logger.error(msg)


def exception(msg):
    _logger.exception(msg)
