"""RAG store constants (ADR-0013)."""

# Output dimensionality of Google `text-embedding-004`. This is baked
# into the `rag_chunks.embedding` column type (Vector(EMBEDDING_DIM)), so
# changing it means re-embedding the whole corpus AND an online column
# migration — it lives as a constant, not a runtime knob. Keep in sync
# with Settings.rag_embedding_model.
EMBEDDING_DIM = 768
