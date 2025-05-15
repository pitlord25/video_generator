import logging
import os
import sys
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal
from logging.handlers import RotatingFileHandler

# Create logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)

class LogHandler(logging.Handler):
    """Custom log handler to forward log messages to the UI"""
    
    def __init__(self, callback):
        """
        Initialize log handler with callback function
        
        Args:
            callback: Function to call for each log message
        """
        super().__init__()
        self.callback = callback
        
        # Set formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        self.setFormatter(formatter)
    
    def emit(self, record):
        """
        Emit a log record
        
        Args:
            record: Log record to emit
        """
        try:
            msg = self.format(record)
            self.callback(msg)
        except Exception:
            self.handleError(record)


def setup_logger():
    """
    Set up and configure the logger
    
    Returns:
        Configured logger instance
    """
    # Create logger
    logger = logging.getLogger("VideoGenerator")
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Create file handler
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_handler = RotatingFileHandler(
        f"logs/video_generator_{timestamp}.log",
        maxBytes=5*1024*1024,  # 5 MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    
    # Create formatters
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Set formatters
    console_handler.setFormatter(console_formatter)
    file_handler.setFormatter(file_formatter)
    
    # Add handlers to logger
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    logger.info("Logger initialized")
    return logger


class LoggingStream:
    """
    Stream-like object that logs the written data
    
    This can be used to capture stdout/stderr and redirect to logger
    """
    
    def __init__(self, logger, log_level=logging.INFO):
        """
        Initialize logging stream
        
        Args:
            logger: Logger to use
            log_level: Logging level
        """
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''
    
    def write(self, buf):
        """
        Write data to the stream
        
        Args:
            buf: Data to write
        """
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())
    
    def flush(self):
        """Flush the stream (no-op)"""
        pass


def redirect_stdout_stderr(logger):
    """
    Redirect stdout and stderr to logger
    
    Args:
        logger: Logger to use
    """
    sys.stdout = LoggingStream(logger, logging.INFO)
    sys.stderr = LoggingStream(logger, logging.ERROR)
    logger.info("Redirected stdout and stderr to logger")


def get_log_files():
    """
    Get list of log files
    
    Returns:
        List of log file paths
    """
    log_files = []
    try:
        for file in os.listdir("logs"):
            if file.endswith(".log"):
                log_files.append(os.path.join("logs", file))
    except Exception as e:
        pass
    
    return sorted(log_files, reverse=True)


def clear_logs(keep_latest=5):
    """
    Clear old log files, keeping the latest ones
    
    Args:
        keep_latest: Number of latest logs to keep
    """
    log_files = get_log_files()
    
    # Keep the specified number of latest logs
    for file in log_files[keep_latest:]:
        try:
            os.remove(file)
        except Exception:
            pass