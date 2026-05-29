package com.lukk.ascend.ai.agent.service.ingestion;

/**
 * Shared metadata keys stamped onto {@link org.springframework.ai.document.Document} objects
 * by every ingestion producer (Markdown, Docling, PaddleOCR, Unstructured) and read back by
 * RAG retrieval and source-file presigning.
 *
 * <p>Per-protocol keys (e.g., PaddleOCR's {@code "lines"} / {@code "pages"} JSON keys,
 * Docling's {@code "md_content"}) belong on their client classes — they are not metadata
 * shared across the pipeline.
 */
public final class IngestionMetadataKeys {

    public static final String SOURCE = "source";
    public static final String TYPE = "type";
    public static final String TITLE = "title";

    private IngestionMetadataKeys() {
    }
}
