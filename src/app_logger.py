import logging
from logging.handlers import RotatingFileHandler

PROTOKOLL_MAX_BYTES = 5 * 1024 * 1024     # darüber beginnt eine neue Datei, die vorherige bleibt als .1


class AppLogger:
    def __init__(self):
        self.logger = logging.getLogger("DocManager")
        self.logger.setLevel(logging.INFO)

        self.log_file = None

        self.fh = None
        self.formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    def set_log_file(self, log_file):
        self.log_file = log_file

        # Falls schon ein Log geschrieben wird, erst schließen
        if self.fh:
            self.logger.removeHandler(self.fh)
            self.fh.close()
            
        self.fh = RotatingFileHandler(log_file, maxBytes=PROTOKOLL_MAX_BYTES, backupCount=1, encoding='utf-8')
        self.fh.setLevel(logging.INFO)
        self.fh.setFormatter(self.formatter)
        self.logger.addHandler(self.fh)

    def info(self, message):
        self.logger.info(message)
        
    def warning(self, message):
        self.logger.warning(message)
        
    def error(self, message):
        self.logger.error(message)