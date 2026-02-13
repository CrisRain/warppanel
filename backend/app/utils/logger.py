import logging
import asyncio
from collections import deque
from datetime import datetime

# Filter for noisy connection logs
class ConnectionFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        return "connection open" not in msg and "connection closed" not in msg

# Custom handler
class LogCollector(logging.Handler):
    def __init__(self, maxlen=100):
        super().__init__()
        self.logs = deque(maxlen=maxlen)
        self._pending_logs: deque = deque(maxlen=maxlen)
        self.formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        self._loop = None
        self._flush_scheduled = False
    
    def set_loop(self, loop):
        """设置事件循环引用"""
        self._loop = loop
    
    def emit(self, record):
        # Get the raw message
        msg = record.getMessage()
        
        # Append exception info if available
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatter.formatException(record.exc_info)
            if record.exc_text:
                msg = f"{msg}\n{record.exc_text}"

        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            'level': record.levelname,
            'logger': record.name,
            'message': msg
        }
        self.logs.append(log_entry)
        self._pending_logs.append(log_entry)
        
        # Schedule a single flush instead of one task per log line
        if not self._flush_scheduled:
            self._flush_scheduled = True
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(self._schedule_flush)
            except Exception:
                self._flush_scheduled = False
    
    def _schedule_flush(self):
        asyncio.create_task(self._flush_pending_logs())
    
    async def _flush_pending_logs(self):
        """Batch-broadcast pending logs to reduce task creation overhead"""
        await asyncio.sleep(0.1)  # 100ms debounce
        self._flush_scheduled = False
        
        # We need a way to broadcast. Ideally via clarity of dependency injection or a global event bus.
        # For now, we will rely on a global manager set by main.py
        if hasattr(self, 'manager') and self.manager:
             while self._pending_logs:
                entry = self._pending_logs.popleft()
                await self.manager.broadcast({'type': 'log', 'data': entry})

# Global instance
log_collector = LogCollector(maxlen=200)

def setup_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # Add collector to root logger
    root_logger = logging.getLogger()
    if log_collector not in root_logger.handlers:
        root_logger.addHandler(log_collector)

    # Apply filter to ALL handlers (console + collector)
    conn_filter = ConnectionFilter()
    for handler in root_logger.handlers:
        handler.addFilter(conn_filter)
        
    # Also suppress uvicorn access logs if needed
    logging.getLogger("uvicorn.access").addFilter(conn_filter)
    logging.getLogger("uvicorn.error").addFilter(conn_filter)
