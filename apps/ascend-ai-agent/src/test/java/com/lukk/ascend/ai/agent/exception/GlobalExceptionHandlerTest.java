package com.lukk.ascend.ai.agent.exception;

import org.assertj.core.api.InstanceOfAssertFactories;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

@ExtendWith(MockitoExtension.class)
class GlobalExceptionHandlerTest {

    @InjectMocks
    private GlobalExceptionHandler globalExceptionHandler;

    @Test
    @DisplayName("handleUnsupportedFileType returns 400 with the unsupported extension in message")
    void handleUnsupportedFileType_Returns400() {
        // given
        UnsupportedFileTypeException exception = new UnsupportedFileTypeException("exe");

        // when
        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleUnsupportedFileType(exception);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody())
                .containsEntry("status", 400)
                .containsEntry("error", "Bad Request")
                .extractingByKey("message", InstanceOfAssertFactories.STRING)
                .contains("exe");
    }

    @Test
    @DisplayName("handleDocumentRouting returns 422 Unprocessable Entity")
    void handleDocumentRouting_Returns422() {
        // given
        DocumentRoutingException exception = new DocumentRoutingException("routing failed");

        // when
        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleDocumentRouting(exception);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody()).containsEntry("status", 422);
        assertThat(response.getBody()).containsEntry("error", "Unprocessable Entity");
    }

    @Test
    @DisplayName("handleIngestion returns 502 Bad Gateway")
    void handleIngestion_Returns502() {
        // given
        IngestionException exception = new IngestionException("ingestion failed", new RuntimeException());

        // when
        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleIngestion(exception);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody()).containsEntry("status", 502);
    }

    @Test
    @DisplayName("handleAiGeneration returns 500 Internal Server Error")
    void handleAiGeneration_Returns500() {
        // given
        AiGenerationException exception = new AiGenerationException("ai failed");

        // when
        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleAiGeneration(exception);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).containsEntry("status", 500);
    }

    @Test
    @DisplayName("handleUnsupportedFileType response contains a non-blank timestamp")
    void handleUnsupportedFileType_ResponseContainsTimestamp() {
        // given
        UnsupportedFileTypeException exception = new UnsupportedFileTypeException("xyz");

        // when
        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleUnsupportedFileType(exception);

        // then
        assertThat(response.getBody())
                .isNotNull()
                .containsKey("timestamp")
                .extractingByKey("timestamp", InstanceOfAssertFactories.type(Object.class))
                .extracting(Object::toString, InstanceOfAssertFactories.STRING)
                .isNotBlank();
    }
}
