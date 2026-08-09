"""
Routing-specific building blocks (Module 8 / Phase 8).

Deliberately separate from `services/routing_service.py`: this package holds
pure, dependency-free logic (keyword matching, department taxonomy, sender
domain classification, rule evaluation) that is independently unit-testable
without constructing any of the five upstream ML services. `RoutingService`
composes these with the upstream services -- same "pure logic vs. service
wiring" split `app/nlp/` uses for summarization (Module 5).
"""
