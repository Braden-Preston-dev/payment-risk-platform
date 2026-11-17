from functools import lru_cache
from typing import Protocol

from redis import Redis

from app.core.config import settings


class RedisClient(Protocol):
    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
        health_check_interval=30,
    )


def close_redis() -> None:
    if get_redis.cache_info().currsize:
        get_redis().close()
        get_redis.cache_clear()
