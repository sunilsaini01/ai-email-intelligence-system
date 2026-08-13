"""
Explicit Kafka topic creation, run once at process startup.

Why this exists: `topics.all_agent_topics()` was written (Phase 12) with a
docstring saying it exists "for topic auto-creation / admin bootstrapping"
but was never actually called anywhere -- confirmed by a dead-code sweep
(grep across the whole backend found only its own definition). The
practical consequence, reproduced live: the Orchestrator's first-ever
publish to `workflow.completed` (a topic nothing had produced to before
that point) logged repeated `Topic workflow.completed not found in
cluster metadata` errors from aiokafka while the broker's implicit
auto-creation caught up. Harmless here only because Kafka's default
auto.create.topics.enable happened to be on for this dev broker -- a real
production cluster commonly disables it, which would turn this from a
transient log warning into a hard publish failure. Creating every topic
explicitly at startup removes the dependency on that broker setting
entirely, for both entrypoints that touch Kafka (see callers).
"""

import logging

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from app.core.config import get_settings
from app.messaging.topics import all_agent_topics

logger = logging.getLogger("app.messaging.topic_admin")


async def ensure_topics_exist() -> None:
    settings = get_settings()
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        new_topics = [
            NewTopic(name=name, num_partitions=1, replication_factor=1) for name in all_agent_topics()
        ]
        try:
            await admin.create_topics(new_topics)
            logger.info("kafka_topics_ensured", extra={"topic_count": len(new_topics)})
        except TopicAlreadyExistsError:
            # Expected on every restart after the first -- topics are
            # already there from a prior run. Not an error.
            logger.info("kafka_topics_already_exist")
    finally:
        await admin.close()
