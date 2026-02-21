import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# Generate timestamp once when module is imported (unique per run)
_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def setup_logger(
    name: str,
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True,
    use_timestamp: bool = True,
    use_rotation: bool = False,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    use_timed_rotation: bool = False,
    when: str = "midnight",
    interval: int = 1,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    
    # Clear existing handlers to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()
    
    # Format for logs
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
    
    # Console handler with Rich formatting
    if log_to_console:
        console_handler = RichHandler(
            rich_tracebacks=True,
            markup=True,
            show_time=True,
            show_path=True,
        )
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(console_handler)
    
    # File handler
    if log_to_file:
        # Determine filename
        if use_timestamp:
            log_file = _LOG_DIR / f"{name.replace('.', '_')}_{_TIMESTAMP}.log"
        else:
            log_file = _LOG_DIR / f"{name.replace('.', '_')}.log"
        
        # Choose handler type
        if use_timed_rotation:
            file_handler = TimedRotatingFileHandler(
                log_file,
                when=when,
                interval=interval,
                backupCount=backup_count,
                encoding="utf-8",
            )
        elif use_rotation:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
        else:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
        
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        logger.debug(f"Logging to file: {log_file}")
        
        for noisy in (
        "httpx", "httpcore", "urllib3", "openai",
        "langchain", "langchain_core", "langchain_groq",
        "langgraph", "langsmith",
        "qdrant_client", "fastembed", "grpc", "PIL", "matplotlib",
    ):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    
    return logger


def get_logger(name: str, **kwargs) -> logging.Logger:
    """
    Get or create a logger with the given name.
    Convenience wrapper around setup_logger.
    """
    return setup_logger(name, **kwargs)


def cleanup_old_logs(days_to_keep: int = 30) -> None:
    """
    Clean up log files older than specified days.
    
    Args:
        days_to_keep: Number of days to keep logs (default: 30)
    """
    from datetime import timedelta
    
    cutoff_time = datetime.now() - timedelta(days=days_to_keep)
    deleted_count = 0
    
    for log_file in _LOG_DIR.glob("*.log*"):
        if log_file.is_file():
            file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_mtime < cutoff_time:
                try:
                    log_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"Failed to delete {log_file}: {e}")
    
    if deleted_count > 0:
        print(f"Cleaned up {deleted_count} old log file(s)")


# Simple default logger for quick use
default_logger = setup_logger("data_compliance_agent")

