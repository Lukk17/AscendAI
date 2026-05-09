package com.lukk.ascend.ai.agent.exception;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.retry.NonTransientAiException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class GlobalExceptionHandlerExtraTest {

    @InjectMocks
    private GlobalExceptionHandler handler;

    @Test
    void handleIncompatibleEmbedding_Returns400() {
        IncompatibleEmbeddingException ex = new IncompatibleEmbeddingException("openai", "lmstudio", 768, 1536);

        ResponseEntity<Map<String, Object>> response = handler.handleIncompatibleEmbedding(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).containsEntry("status", 400);
        assertThat(response.getBody().get("message").toString()).contains("openai", "lmstudio");
    }

    @Test
    void handleIllegalArgument_Returns400() {
        ResponseEntity<Map<String, Object>> response = handler.handleIllegalArgument(
                new IllegalArgumentException("bad arg"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).containsEntry("status", 400);
        assertThat(response.getBody()).containsEntry("message", "bad arg");
    }

    @Test
    void handleGenericException_Returns500_WithSanitizedMessage() {
        ResponseEntity<Map<String, Object>> response = handler.handleGenericException(
                new RuntimeException("internal trace with secrets"));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody().get("message").toString())
                .doesNotContain("secrets")
                .contains("unexpected error");
    }

    @Test
    void handleNonTransientAi_Returns502_When401ProviderError() {
        NonTransientAiException ex = new NonTransientAiException("401 - Unauthorized");

        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody().get("message").toString()).contains("AI provider error");
    }

    @Test
    void handleNonTransientAi_Returns429_When429ProviderError() {
        NonTransientAiException ex = new NonTransientAiException("429 Too Many Requests");

        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    void handleNonTransientAi_Returns502_WhenUnknownStatusCode() {
        NonTransientAiException ex = new NonTransientAiException("Some other failure");

        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
    }

    @Test
    void handleNonTransientAi_TruncatesJsonPayloadInMessage() {
        NonTransientAiException ex = new NonTransientAiException(
                "503 Bad upstream {\"error\": \"secret-key-leaked-here\"}");

        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        assertThat(response.getBody().get("message").toString())
                .doesNotContain("secret-key-leaked-here")
                .startsWith("AI provider error:");
    }

    @Test
    void handleNonTransientAi_HandlesNullMessage() {
        NonTransientAiException ex = new NonTransientAiException(null);

        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody().get("message").toString())
                .isEqualTo("AI provider returned an error");
    }
}
