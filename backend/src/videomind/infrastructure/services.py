import urllib3
from minio import Minio
from redis import Redis

from videomind.config import Settings


def redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_url.get_secret_value(),
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def object_client(settings: Settings) -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=False,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=2, read=2), retries=False
        ),
    )
