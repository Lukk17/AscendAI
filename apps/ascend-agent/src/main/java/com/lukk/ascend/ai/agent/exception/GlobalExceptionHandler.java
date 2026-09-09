package com.lukk.ascend.ai.agent.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.retry.NonTransientAiException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.Instant;
import java.util.Map;

@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(IncompatibleEmbeddingException.class)
    public ResponseEntity<Map<String, Object>> handleIncompatibleEmbedding(IncompatibleEmbeddingException ex) {
        log.warn("[GlobalExceptionHandler] Incompatible embedding configuration: {}", ex.getMessage());
        return buildResponse(HttpStatus.BAD_REQUEST, ex.getMessage());
    }

    @ExceptionHandler(UnsupportedFileTypeException.class)
    public ResponseEntity<Map<String, Object>> handleUnsupportedFileType(UnsupportedFileTypeException ex) {
        log.warn("[GlobalExceptionHandler] Unsupported file type: {}", ex.getMessage());
        return buildResponse(HttpStatus.BAD_REQUEST, ex.getMessage());
    }

    @ExceptionHandler(DocumentRoutingException.class)
    public ResponseEntity<Map<String, Object>> handleDocumentRouting(DocumentRoutingException ex) {
        log.error("[GlobalExceptionHandler] Document routing failed: {}", ex.getMessage(), ex);
        return buildResponse(HttpStatus.UNPROCESSABLE_ENTITY, ex.getMessage());
    }

    @ExceptionHandler(IngestionException.class)
    public ResponseEntity<Map<String, Object>> handleIngestion(IngestionException ex) {
        log.error("[GlobalExceptionHandler] Ingestion failed: {}", ex.getMessage(), ex);
        return buildResponse(HttpStatus.BAD_GATEWAY, ex.getMessage());
    }

    @ExceptionHandler(AiGenerationException.class)
    public ResponseEntity<Map<String, Object>> handleAiGeneration(AiGenerationException ex) {
        log.error("[GlobalExceptionHandler] AI generation failed: {}", ex.getMessage(), ex);
        return buildResponse(HttpStatus.INTERNAL_SERVER_ERROR, ex.getMessage());
    }

    @ExceptionHandler(NonTransientAiException.class)
    public ResponseEntity<Map<String, Object>> handleNonTransientAi(NonTransientAiException ex) {
        log.error("[GlobalExceptionHandler] AI provider error (non-transient): {}", ex.getMessage());
        HttpStatus status = extractHttpStatus(ex.getMessage());
        return buildResponse(status, sanitizeProviderError(ex.getMessage()));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalArgument(IllegalArgumentException ex) {
        log.warn("[GlobalExceptionHandler] Bad request: {}", ex.getMessage());
        return buildResponse(HttpStatus.BAD_REQUEST, ex.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> handleGenericException(Exception ex) {
        log.error("[GlobalExceptionHandler] Unexpected error: {}", ex.getMessage(), ex);
        return buildResponse(HttpStatus.INTERNAL_SERVER_ERROR, "An unexpected error occurred. Check server logs for details.");
    }

    private HttpStatus extractHttpStatus(String message) {
        if (message != null && message.startsWith("401")) {
            return HttpStatus.BAD_GATEWAY;
        }
        if (message != null && message.startsWith("429")) {
            return HttpStatus.TOO_MANY_REQUESTS;
        }
        return HttpStatus.BAD_GATEWAY;
    }

    private String sanitizeProviderError(String message) {
        if (message == null) {
            return "AI provider returned an error";
        }
        int jsonStart = message.indexOf('{');
        if (jsonStart > 0) {
            return "AI provider error: " + message.substring(0, jsonStart).trim();
        }
        return "AI provider error: " + message;
    }

    private ResponseEntity<Map<String, Object>> buildResponse(HttpStatus status, String message) {
        Map<String, Object> body = Map.of(
                "status", status.value(),
                "error", status.getReasonPhrase(),
                "message", message,
                "timestamp", Instant.now().toString());
        return ResponseEntity.status(status).body(body);
    }
}

