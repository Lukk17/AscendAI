package com.lukk.ascend.ai.mcp.weather.exception;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.resource.NoResourceFoundException;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    @DisplayName("Refused path still answers 404 with the path in the body")
    void handleNoResourceFound_AnswersNotFoundWithPath() {
        // given
        var ex = new NoResourceFoundException(HttpMethod.GET, "/e2e-canary-wx");

        // when
        ResponseEntity<Map<String, Object>> response = handler.handleNoResourceFound(ex);

        // then
        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(response.getBody()).isNotNull();
        assertThat(response.getBody().get("status")).isEqualTo(404);
        assertThat(response.getBody().get("message").toString()).contains("/e2e-canary-wx");
    }
}
