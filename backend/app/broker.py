import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.config import get_settings

settings = get_settings()
broker = RedisBroker(url=settings.redis_url, namespace="pdfrag")
dramatiq.set_broker(broker)
