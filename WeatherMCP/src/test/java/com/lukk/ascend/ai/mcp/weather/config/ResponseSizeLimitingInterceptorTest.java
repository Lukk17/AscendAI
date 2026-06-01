package com.lukk.ascend.ai.mcp.weather.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.web.client.RestClientException;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ResponseSizeLimitingInterceptorTest {

    private static final int SMALL_MAX = 10;

    private final ResponseSizeLimitingInterceptor interceptor = new ResponseSizeLimitingInterceptor(SMALL_MAX);

    @Test
    @DisplayName("throws RestClientException when Content-Length header exceeds max bytes")
    void intercept_contentLengthExceedsMax_throwsRestClientException() throws IOException {
        // given
        try (ClientHttpResponse response = buildResponse(SMALL_MAX + 1, "hello")) {
            ClientHttpRequestExecution execution = (req, body) -> response;

            // then
            assertThatThrownBy(() -> interceptor.intercept(mockRequest(), new byte[0], execution))
                    .isInstanceOf(RestClientException.class)
                    .hasMessageContaining("advertised");
            verify(response).close();
        }
    }

    @Test
    @DisplayName("throws RestClientException when body bytes exceed max even with no Content-Length header")
    void intercept_bodyExceedsMax_throwsRestClientException() throws IOException {
        // given
        String bigBody = "x".repeat(SMALL_MAX + 1);
        try (ClientHttpResponse response = buildResponse(-1, bigBody)) {
            ClientHttpRequestExecution execution = (req, body) -> response;

            // then
            assertThatThrownBy(() -> interceptor.intercept(mockRequest(), new byte[0], execution))
                    .isInstanceOf(RestClientException.class)
                    .hasMessageContaining("read past");
            verify(response).close();
        }
    }

    @Test
    @DisplayName("returns the response unchanged when Content-Length is within max and body fits")
    void intercept_contentLengthWithinMax_returnsResponse() throws IOException {
        // given
        String payload = "hello";
        try (ClientHttpResponse response = buildResponse(payload.length(), payload)) {
            ClientHttpRequestExecution execution = (req, body) -> response;

            // when
            ClientHttpResponse result = interceptor.intercept(mockRequest(), new byte[0], execution);

            // then
            assertThat(result).isSameAs(response);
        }
    }

    @Test
    @DisplayName("returns the response unchanged when Content-Length is absent and body fits within max")
    void intercept_noContentLengthBodyFits_returnsResponse() throws IOException {
        // given
        String payload = "hi";
        try (ClientHttpResponse response = buildResponse(-1, payload)) {
            ClientHttpRequestExecution execution = (req, body) -> response;

            // when
            ClientHttpResponse result = interceptor.intercept(mockRequest(), new byte[0], execution);

            // then
            assertThat(result).isSameAs(response);
        }
    }

    @Test
    @DisplayName("default constructor creates interceptor with DEFAULT_MAX_BYTES limit")
    void defaultConstructor_usesDefaultMaxBytes() {
        // when
        ResponseSizeLimitingInterceptor defaultInterceptor = new ResponseSizeLimitingInterceptor();

        // then
        assertThat(defaultInterceptor).isNotNull();
        assertThat(ResponseSizeLimitingInterceptor.DEFAULT_MAX_BYTES).isEqualTo(256 * 1024);
    }

    private static ClientHttpResponse buildResponse(long contentLength, String body) throws IOException {
        ClientHttpResponse response = mock(ClientHttpResponse.class);
        HttpHeaders headers = new HttpHeaders();
        if (contentLength >= 0) {
            headers.setContentLength(contentLength);
        }
        when(response.getHeaders()).thenReturn(headers);
        when(response.getStatusCode()).thenReturn(HttpStatus.OK);
        InputStream bodyStream = new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));
        when(response.getBody()).thenReturn(bodyStream);

        return response;
    }

    private static HttpRequest mockRequest() {
        HttpRequest request = mock(HttpRequest.class);
        when(request.getHeaders()).thenReturn(new HttpHeaders());

        return request;
    }
}
