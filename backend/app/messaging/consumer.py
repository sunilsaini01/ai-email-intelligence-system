"""
Kafka consumer construction + the generic consume loop every agent and the
orchestrator run on top of.

Delivery semantics: at-least-once, by deliberate choice (FR-65's
`docs/kafka_architecture.md` "Delivery Semantics"). `enable_auto_commit`
is False and the offset is committed only AFTER the handler returns
successfully -- a crash between a successful handler run and the commit
re-delivers that message on restart, which is why every agent's handler
must be idempotent (see app/agents/base.py's duplicate-detection check,
not a new mechanism invented here). The alternative (commit-before-handle,
i.e. at-most-once) would silently drop a message on a crash mid-handler,
which is worse for this system: a silently-skipped classification is a
correctness bug, a redundantly-reprocessed one is just wasted work that
idempotency already absorbs.
"""

import logging
from collections.abc import Awaitable, Callable

from aiokafka import AIOKafkaConsumer

from app.core.config import get_settings

logger = logging.getLogger("app.messaging.consumer")


def build_consumer(*topics: str, group_id: str) -> AIOKafkaConsumer:
    settings = get_settings()
    return AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )


async def consume_forever(
    consumer: AIOKafkaConsumer,
    handler: Callable[[bytes], Awaitable[None]],
) -> None:
    """Runs until the consumer is stopped/cancelled. `handler` is expected
    to catch and internally resolve its own retryable failures (an
    agent's own retry/backoff/DLQ logic -- see app/agents/base.py) and
    only ever raise for a genuinely unexpected bug in the harness itself.
    On that rare path, the message is deliberately NOT committed --
    redelivering it on restart is the safer default (never silently drop
    a message, per Critical Rule: 'treat distributed systems failures as
    normal operating conditions') even though a truly broken handler would
    then redeliver-and-fail in a loop until the underlying bug is fixed.
    """
    await consumer.start()
    try:
        async for message in consumer:
            try:
                await handler(message.value)
            except Exception:
                logger.error(
                    "consumer_handler_failed_message_not_committed",
                    exc_info=True,
                    extra={"topic": message.topic, "partition": message.partition, "offset": message.offset},
                )
            else:
                await consumer.commit()
    finally:
        await consumer.stop()
