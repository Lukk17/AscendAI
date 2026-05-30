package com.lukk.ascend.ai.mcp.weather.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
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
import static org.mockito.Mockito.when;

class ResponseSizeLimitingInterceptorTest {

    private static final int SMALL_MAX = 10;

    private final ResponseSizeLimitingInterceptor interceptor = new ResponseSizeLimitingInterceptor(SMALL_MAX);

    @Test
    @DisplayName("throws RestClientException when Content-Length header exceeds max bytes")
    void intercept_contentLengthExceedsMax_throwsRestClientException() throws IOException {
        // given
        ClientHttpResponse response = buildResponse(SMALL_MAX + 1, "hello");
        ClientHttpRequestExecution execution = (req, body) -> response;

        // then
        assertThatThrownBy(() -> interceptor.intercept(mockRequest(), new byte[0], execution))
                .isInstanceOf(RestClientException.class)
                .hasMessageContaining("advertised");
    }

    @Test
    @DisplayName("throws RestClientException when body bytes exceed max even with no Content-Length header")
    void intercept_bodyExceedsMax_throwsRestClientException() throws IOException {
        // given — body is larger than SMALL_MAX; Content-Length is -1 (unset)
        byte[] bigBody = "x".repeat(SMALL_MAX + 1).getBytes(StandardCharsets.UTF_8);
        ClientHttpResponse response = buildResponse(-1, new String(bigBody, StandardCharsets.UTF_8));
        ClientHttpRequestExecution execution = (req, body) -> response;

        // then
        assertThatThrownBy(() -> interceptor.intercept(mockRequest(), new byte[0], execution))
                .isInstanceOf(RestClientException.class)
                .hasMessageContaining("read past");
    }

    @Test
    @DisplayName("passes through when Content-Length is within max and body fits")
    void intercept_contentLengthWithinMax_returnsBufferedResponse() throws IOException {
        // given
        String payload = "hello";
        ClientHttpResponse response = buildResponse(payload.length(), payload);
        ClientHttpRequestExecution execution = (req, body) -> response;

        // when
        ClientHttpResponse result = interceptor.intercept(mockRequest(), new byte[0], execution);

        // then
        byte[] read = result.getBody().readAllBytes();
        assertThat(new String(read, StandardCharsets.UTF_8)).isEqualTo(payload);
    }

    @Test
    @DisplayName("passes through when Content-Length is absent and body fits within max")
    void intercept_noContentLengthBodyFits_returnsBufferedResponse() throws IOException {
        // given — Content-Length header absent (-1); body is small
        String payload = "hi";
        ClientHttpResponse response = buildResponse(-1, payload);
        ClientHttpRequestExecution execution = (req, body) -> response;

        // when
        ClientHttpResponse result = interceptor.intercept(mockRequest(), new byte[0], execution);

        // then
        byte[] read = result.getBody().readAllBytes();
        assertThat(new String(read, StandardCharsets.UTF_8)).isEqualTo(payload);
    }

    @Test
    @DisplayName("default constructor creates interceptor with DEFAULT_MAX_BYTES limit")
    void defaultConstructor_usesDefaultMaxBytes() {
        ResponseSizeLimitingInterceptor defaultInterceptor = new ResponseSizeLimitingInterceptor();
        assertThat(ResponseSizeLimitingInterceptor.DEFAULT_MAX_BYTES).isEqualTo(256 * 1024);
    }

    @Test
    @DisplayName("buffered response delegates getStatusCode, getStatusText, getHeaders, close to the underlying response")
    void bufferedResponse_delegatesNonBodyMethodsToUnderlyingResponse() throws IOException {
        // given
        ClientHttpResponse underlying = mock(ClientHttpResponse.class);
        HttpHeaders headers = new HttpHeaders();
        headers.setContentLength(2);
        when(underlying.getHeaders()).thenReturn(headers);
        when(underlying.getStatusCode()).thenReturn(HttpStatus.ACCEPTED);
        when(underlying.getStatusText()).thenReturn("Accepted");
        when(underlying.getBody()).thenReturn(new ByteArrayInputStream("ok".getBytes(StandardCharsets.UTF_8)));
        ClientHttpRequestExecution execution = (req, body) -> underlying;

        // when
        ClientHttpResponse wrapped = interceptor.intercept(mockRequest(), new byte[0], execution);

        // then
        assertThat(wrapped.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        assertThat(wrapped.getStatusText()).isEqualTo("Accepted");
        assertThat(wrapped.getHeaders()).isSameAs(headers);

        // and — close() delegates to the underlying response without throwing
        wrapped.close();
        org.mockito.Mockito.verify(underlying).close();
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

    private static org.springframework.http.HttpRequest mockRequest() {
        org.springframework.http.HttpRequest request = mock(org.springframework.http.HttpRequest.class);
        when(request.getHeaders()).thenReturn(new HttpHeaders());

        return request;
    }
}
