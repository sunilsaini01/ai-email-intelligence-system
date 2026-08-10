"""
Kafka producer lifecycle + publish helper.

Why a module-level singleton started/stopped from app lifespan (mirrors
app/main.py's existing ML-service warmup pattern) rather than constructing
an AIOKafkaProducer per call: AIOKafkaProducer.start() opens a real
network connection and does broker metadata discovery -- paying that cost
per-publish would be the same mistake Phase 10 already found and fixed for
the retrieval embedder/vector-store (docs/architecture_auto_reply.md
"Embedder Decision" -- reconstructed on every call, ~1.4s/request cost
before the fix). One producer per process, reused for every publish.
"""

import logging

from aiokafka import AIOKafkaProducer

from app.core.config import get_settings
from app.messaging.schemas import AgentEvent, DeadLetterEnvelope

logger = logging.getLogger("app.messaging.producer")

_producer: AIOKafkaProducer | None = None


async def start_producer() -> None:
    global _producer
    if _producer is not None:
        return
    settings = get_settings()
    _producer = AIOKafkaProducer(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await _producer.start()
    logger.info("kafka_producer_started")


async def stop_producer() -> None:
    global _producer
    if _producer is None:
        return
    await _producer.stop()
    _producer = None
    logger.info("kafka_producer_stopped")


def get_producer() -> AIOKafkaProducer:
    if _producer is None:
        raise RuntimeError(
            "Kafka producer not started -- start_producer() must be awaited during app "
            "startup (see app/main.py lifespan) before publish_event() can be called."
        )
    return _producer


async def publish_event(topic: str, event: AgentEvent) -> None:
    """Keyed by email_id (see docs/kafka_architecture.md 'Partitioning') --
    guarantees every event about one email lands on the same partition,
    giving per-email ordering without needing a global order."""
    producer = get_producer()
    await producer.send_and_wait(
        topic,
        value=event.to_kafka_value(),
        key=str(event.email_id).encode("utf-8"),
    )


async def publish_dead_letter(topic: str, envelope: DeadLetterEnvelope) -> None:
    """Same keying reasoning as publish_event -- keeps a failed email's DLQ
    entry on the same partition as the rest of its events, for an operator
    reading the log in order."""
    producer = get_producer()
    await producer.send_and_wait(
        topic,
        value=envelope.to_kafka_value(),
        key=str(envelope.original_event.email_id).encode("utf-8"),
    )
