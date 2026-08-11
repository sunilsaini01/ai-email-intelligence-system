"""
Entrypoint: `python -m app.agents.runner` (docker-compose's `agents`
service, see docker-compose.yml).

Why one process running seven consumer tasks (6 specialist agents +
Orchestrator) instead of seven separate containers/processes: at this
project's current scale (a local dev/demo deployment, zero production
traffic -- same standing status every other phase discloses), seven
processes would be seven times the memory footprint for loading each
ML module's artifacts, with no real concurrency benefit this codebase's
actual load justifies. Each agent still gets its OWN Kafka consumer group
(see messaging/consumer.py's build_consumer, `f"{prefix}-{agent_name}"`),
so splitting them into separate processes/containers later -- for real
horizontal scaling, when there's evidence it's needed -- is purely an
infrastructure change (run this same module N times with different
`AGENT_NAME` filters), not a code rewrite. Same "the layering exists now,
extraction later is a refactor, not a rewrite" philosophy
docs/architecture.md already established for the services/ layer.
"""

# Import-order workaround (Phase 9, restated for this SEPARATE entrypoint):
# this module is started directly (`python -m app.agents.runner`, see
# docker-compose.yml's `agents` service `command`), not via app/main.py --
# so app/main.py's own top-of-file `import pandas; import sklearn` guard
# (see that file's module docstring for the full explanation and the exact
# Windows fault it prevents: transformers' lazy-module `__getattr__`
# resolving a sklearn/pandas/pyarrow import for the first time when
# summarization and retrieval both end up in the same import sweep) does
# NOT run before this module imports every specialist agent below,
# including summarization_agent (pulls in transformers) alongside
# category_agent/priority_agent/etc. (pull in sklearn) and, via the
# Orchestrator, retrieval_service. Reproduced directly: omitting this
# caused a real segfault (exit 139) running this exact module standalone.
import asyncio
import logging
import signal

import pandas  # noqa: F401,E402
import sklearn  # noqa: F401,E402

from app.agents.category_agent import CategoryAgent
from app.agents.intent_agent import IntentAgent
from app.agents.orchestrator import Orchestrator
from app.agents.priority_agent import PriorityAgent
from app.agents.sentiment_agent import SentimentAgent
from app.agents.spam_agent import SpamAgent
from app.agents.summarization_agent import SummarizationAgent
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.messaging import topics
from app.messaging.consumer import build_consumer, consume_forever
from app.messaging.producer import start_producer, stop_producer

logger = logging.getLogger("app.agents.runner")

SPECIALIST_AGENTS = (
    SpamAgent,
    PriorityAgent,
    CategoryAgent,
    SentimentAgent,
    IntentAgent,
    SummarizationAgent,
)


async def _run_specialist(agent_cls) -> None:
    agent = agent_cls()
    settings = get_settings()
    consumer = build_consumer(
        topics.requested_topic(agent.agent_name),
        group_id=f"{settings.KAFKA_CONSUMER_GROUP_PREFIX}-{agent.agent_name}",
    )
    logger.info("agent_consumer_starting", extra={"agent": agent.agent_name})
    await consume_forever(consumer, agent.handle_message)


async def _run_orchestrator() -> None:
    orchestrator = Orchestrator()
    settings = get_settings()
    consumer = build_consumer(
        *orchestrator.consumer_topics(),
        group_id=f"{settings.KAFKA_CONSUMER_GROUP_PREFIX}-{orchestrator.consumer_group}",
    )
    logger.info("orchestrator_consumer_starting")
    await consume_forever(consumer, orchestrator.handle_message)


async def main() -> None:
    setup_logging()
    await start_producer()

    tasks = [asyncio.create_task(_run_specialist(cls)) for cls in SPECIALIST_AGENTS]
    tasks.append(asyncio.create_task(_run_orchestrator()))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows local dev (non-Docker `python -m app.agents.runner`) -- Ctrl+C still raises KeyboardInterrupt

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("agents_runner_shutting_down")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await stop_producer()


if __name__ == "__main__":
    asyncio.run(main())
