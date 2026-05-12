package com.lukk.ascend.ai.agent.exception;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CustomExceptionsTest {

    @Test
    void aiGenerationException_MessageOnly() {
        AiGenerationException ex = new AiGenerationException("ai down");

        assertThat(ex.getMessage()).isEqualTo("ai down");
        assertThat(ex.getCause()).isNull();
    }

    @Test
    void aiGenerationException_MessageAndCause() {
        Throwable cause = new IllegalStateException("root");
        AiGenerationException ex = new AiGenerationException("wrapped", cause);

        assertThat(ex.getMessage()).isEqualTo("wrapped");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @Test
    void documentRoutingException_MessageOnly() {
        DocumentRoutingException ex = new DocumentRoutingException("route fail");

        assertThat(ex.getMessage()).isEqualTo("route fail");
        assertThat(ex.getCause()).isNull();
    }

    @Test
    void documentRoutingException_MessageAndCause() {
        Throwable cause = new RuntimeException("io");
        DocumentRoutingException ex = new DocumentRoutingException("rt", cause);

        assertThat(ex.getMessage()).isEqualTo("rt");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @Test
    void ingestionException_MessageOnly() {
        IngestionException ex = new IngestionException("ingest");

        assertThat(ex.getMessage()).isEqualTo("ingest");
        assertThat(ex.getCause()).isNull();
    }

    @Test
    void ingestionException_MessageAndCause() {
        Throwable cause = new RuntimeException("c");
        IngestionException ex = new IngestionException("ingest", cause);

        assertThat(ex.getMessage()).isEqualTo("ingest");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @Test
    void serviceException_MessageOnly() {
        ServiceException ex = new ServiceException("svc");

        assertThat(ex.getMessage()).isEqualTo("svc");
        assertThat(ex.getCause()).isNull();
    }

    @Test
    void serviceException_MessageAndCause() {
        Throwable cause = new RuntimeException("c");
        ServiceException ex = new ServiceException("svc", cause);

        assertThat(ex.getMessage()).isEqualTo("svc");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @Test
    void unsupportedFileTypeException_FormatsMessageWithExtension() {
        UnsupportedFileTypeException ex = new UnsupportedFileTypeException("xyz");

        assertThat(ex.getMessage()).isEqualTo("Filetype is not supported: xyz");
    }

    @Test
    void incompatibleEmbeddingException_BuildsHumanReadableMessage() {
        IncompatibleEmbeddingException ex = new IncompatibleEmbeddingException(
                "openai", "lmstudio", 768, 1536);

        assertThat(ex.getMessage())
                .contains("openai")
                .contains("lmstudio")
                .contains("768-dim")
                .contains("1536-dim")
                .contains("EMBEDDING_PROVIDER");
    }
}
