"""RAG assistant (ADR-0013).

ACL-aware retrieval-augmented Q&A over the org's documents + master data.
This package owns the *separate* pgvector store (its own Postgres
container, never the app DB), the ingestion pipeline, hybrid retrieval
with the backend's visibility filter as a hard pre-filter, and Gemini
generation with required citations + abstain.

Ships dark until `settings.rag_enabled` — see app/main.py lifespan.
"""
