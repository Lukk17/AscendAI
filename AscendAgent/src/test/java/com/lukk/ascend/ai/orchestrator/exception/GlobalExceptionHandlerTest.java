package com.lukk.ascend.ai.orchestrator.exception;

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
    void handleUnsupportedFileType_Returns400() {
        UnsupportedFileTypeException exception = new UnsupportedFileTypeException("exe");

        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleUnsupportedFileType(exception);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(response.getBody()).containsEntry("status", 400);
        assertThat(response.getBody()).containsEntry("error", "Bad Request");
        assertThat(response.getBody().get("message").toString()).contains("exe");
    }

    @Test
    void handleDocumentRouting_Returns422() {
        DocumentRoutingException exception = new DocumentRoutingException("routing failed");

        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleDocumentRouting(exception);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
        assertThat(response.getBody()).containsEntry("status", 422);
        assertThat(response.getBody()).containsEntry("error", "Unprocessable Entity");
    }

    @Test
    void handleIngestion_Returns502() {
        IngestionException exception = new IngestionException("ingestion failed", new RuntimeException());

        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleIngestion(exception);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.BAD_GATEWAY);
        assertThat(response.getBody()).containsEntry("status", 502);
    }

    @Test
    void handleAiGeneration_Returns500() {
        AiGenerationException exception = new AiGenerationException("ai failed");

        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleAiGeneration(exception);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
        assertThat(response.getBody()).containsEntry("status", 500);
    }

    @Test
    void handleUnsupportedFileType_ResponseContainsTimestamp() {
        UnsupportedFileTypeException exception = new UnsupportedFileTypeException("xyz");

        ResponseEntity<Map<String, Object>> response = globalExceptionHandler.handleUnsupportedFileType(exception);

        assertThat(response.getBody()).containsKey("timestamp");
        assertThat(response.getBody().get("timestamp").toString()).isNotBlank();
    }
}
