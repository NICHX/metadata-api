import asyncio
from collections import deque
from typing import List

_buffer: deque = deque(maxlen=2000)
_lock = asyncio.Lock()


async def push_log(message: str) -> None:
    """推送一条日志到缓冲区（异步安全）"""
    async with _lock:
        _buffer.append(message)


def push_log_sync(message: str) -> None:
    """推送一条日志到缓冲区（同步安全，用于非协程上下文）"""
    _buffer.append(message)


async def get_logs(n: int = 500) -> List[str]:
    """获取最近 n 条日志"""
    async with _lock:
        return list(_buffer)[-n:]


def clear_logs() -> None:
    _buffer.clear()