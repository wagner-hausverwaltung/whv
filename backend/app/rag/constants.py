"""RAG store constants (ADR-0013)."""

# Embedding dimensionality. `gemini-embedding-001` emits 3072 dims natively;
# the Gemini provider requests output_dimensionality=EMBEDDING_DIM so the
# vectors fit the `rag_chunks.embedding` column type (Vector(EMBEDDING_DIM)).
# Changing it means re-embedding the whole corpus AND an online column
# migration — it lives as a constant, not a runtime knob. Keep in sync with
# Settings.rag_embedding_model.
EMBEDDING_DIM = 768
