package com.lukk.ascend.ai.agent.exception;

import org.junit.jupiter.api.DisplayName;
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
    @DisplayName("handleIncompatibleEmbedding returns 400 with provider names in message")
    void handleIncompatibleEmbedding_Returns400() {
        // given
        IncompatibleEmbeddingException ex = new IncompatibleEmbeddingException("openai", "lmstudio", 768, 1536);

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleIncompatibleEmbedding(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).containsEntry("status", 400);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("message").toString()).contains("openai", "lmstudio");
    }

    @Test
    @DisplayName("handleIllegalArgument returns 400 with the exception message")
    void handleIllegalArgument_Returns400() {
        // when
        ResponseEntity<Map<String, Object>> response = handler.handleIllegalArgument(
                new IllegalArgumentException("bad arg"));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).containsEntry("status", 400);
        assertThat(response.getBody()).containsEntry("message", "bad arg");
    }

    @Test
    @DisplayName("handleGenericException returns 500 with sanitized message that omits internal details")
    void handleGenericException_Returns500_WithSanitizedMessage() {
        // when
        ResponseEntity<Map<String, Object>> response = handler.handleGenericException(
                new RuntimeException("internal trace with secrets"));

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("message").toString())
                .doesNotContain("secrets")
                .contains("unexpected error");
    }

    @Test
    @DisplayName("handleNonTransientAi returns 502 when provider returns 401")
    void handleNonTransientAi_Returns502_When401ProviderError() {
        // given
        NonTransientAiException ex = new NonTransientAiException("401 - Unauthorized");

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("message").toString()).contains("AI provider error");
    }

    @Test
    @DisplayName("handleNonTransientAi returns 429 when provider returns 429 rate-limit")
    void handleNonTransientAi_Returns429_When429ProviderError() {
        // given
        NonTransientAiException ex = new NonTransientAiException("429 Too Many Requests");

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS);
    }

    @Test
    @DisplayName("handleNonTransientAi returns 502 when provider returns an unknown status code")
    void handleNonTransientAi_Returns502_WhenUnknownStatusCode() {
        // given
        NonTransientAiException ex = new NonTransientAiException("Some other failure");

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
    }

    @Test
    @DisplayName("handleNonTransientAi truncates JSON payload so keys are not leaked to caller")
    void handleNonTransientAi_TruncatesJsonPayloadInMessage() {
        // given
        NonTransientAiException ex = new NonTransientAiException(
                "503 Bad upstream {\"error\": \"secret-key-leaked-here\"}");

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        // then
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("message").toString())
                .doesNotContain("secret-key-leaked-here")
                .startsWith("AI provider error:");
    }

    @Test
    @DisplayName("handleNonTransientAi returns 502 with default message when exception message is null")
    void handleNonTransientAi_HandlesNullMessage() {
        // given
        NonTransientAiException ex = new NonTransientAiException(null);

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNonTransientAi(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("message").toString())
                .isEqualTo("AI provider returned an error");
    }
}
