from dataclasses import dataclass

from redis.exceptions import RedisError

from app.core.redis import RedisClient


_INCREMENT_WITH_TTL = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('PTTL', KEYS[1])
return {current, ttl}
"""


class RateLimitUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class CounterResult:
    count: int
    retry_after_seconds: int


def increment_counter(
    redis: RedisClient,
    *,
    key: str,
    window_seconds: int,
) -> CounterResult:
    try:
        result = redis.eval(
            _INCREMENT_WITH_TTL,
            1,
            key,
            window_seconds * 1000,
        )
    except RedisError as exc:
        raise RateLimitUnavailableError from exc

    count, ttl_ms = (int(value) for value in result)  # type: ignore[arg-type]
    retry_after = max(1, (ttl_ms + 999) // 1000)
    return CounterResult(count=count, retry_after_seconds=retry_after)
