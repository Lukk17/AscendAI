package com.lukk.ascend.ai.agent.exception;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class CustomExceptionsTest {

    @DisplayName("ai generation exception message only")
    @Test
    void aiGenerationException_MessageOnly() {
        // when
        AiGenerationException ex = new AiGenerationException("ai down");

        // then
        assertThat(ex.getMessage()).isEqualTo("ai down");
        assertThat(ex.getCause()).isNull();
    }

    @DisplayName("ai generation exception message and cause")
    @Test
    void aiGenerationException_MessageAndCause() {
        // given
        Throwable cause = new IllegalStateException("root");
        // when
        AiGenerationException ex = new AiGenerationException("wrapped", cause);

        // then
        assertThat(ex.getMessage()).isEqualTo("wrapped");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @DisplayName("document routing exception message only")
    @Test
    void documentRoutingException_MessageOnly() {
        // when
        DocumentRoutingException ex = new DocumentRoutingException("route fail");

        // then
        assertThat(ex.getMessage()).isEqualTo("route fail");
        assertThat(ex.getCause()).isNull();
    }

    @DisplayName("document routing exception message and cause")
    @Test
    void documentRoutingException_MessageAndCause() {
        // given
        Throwable cause = new RuntimeException("io");
        // when
        DocumentRoutingException ex = new DocumentRoutingException("rt", cause);

        // then
        assertThat(ex.getMessage()).isEqualTo("rt");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @DisplayName("ingestion exception message only")
    @Test
    void ingestionException_MessageOnly() {
        // when
        IngestionException ex = new IngestionException("ingest");

        // then
        assertThat(ex.getMessage()).isEqualTo("ingest");
        assertThat(ex.getCause()).isNull();
    }

    @DisplayName("ingestion exception message and cause")
    @Test
    void ingestionException_MessageAndCause() {
        // given
        Throwable cause = new RuntimeException("c");
        // when
        IngestionException ex = new IngestionException("ingest", cause);

        // then
        assertThat(ex.getMessage()).isEqualTo("ingest");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @DisplayName("service exception message only")
    @Test
    void serviceException_MessageOnly() {
        // when
        ServiceException ex = new ServiceException("svc");

        // then
        assertThat(ex.getMessage()).isEqualTo("svc");
        assertThat(ex.getCause()).isNull();
    }

    @DisplayName("service exception message and cause")
    @Test
    void serviceException_MessageAndCause() {
        // given
        Throwable cause = new RuntimeException("c");
        // when
        ServiceException ex = new ServiceException("svc", cause);

        // then
        assertThat(ex.getMessage()).isEqualTo("svc");
        assertThat(ex.getCause()).isSameAs(cause);
    }

    @DisplayName("unsupported file type exception formats message with extension")
    @Test
    void unsupportedFileTypeException_FormatsMessageWithExtension() {
        // when
        UnsupportedFileTypeException ex = new UnsupportedFileTypeException("xyz");

        // then
        assertThat(ex.getMessage()).isEqualTo("Filetype is not supported: xyz");
    }

    @DisplayName("incompatible embedding exception builds human readable message")
    @Test
    void incompatibleEmbeddingException_BuildsHumanReadableMessage() {
        // when
        IncompatibleEmbeddingException ex = new IncompatibleEmbeddingException(
                "openai", "lmstudio", 768, 1536);

        // then
        assertThat(ex.getMessage())
                .contains("openai")
                .contains("lmstudio")
                .contains("768-dim")
                .contains("1536-dim")
                .contains("EMBEDDING_PROVIDER");
    }
}
