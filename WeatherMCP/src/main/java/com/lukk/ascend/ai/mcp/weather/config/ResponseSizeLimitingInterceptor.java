package com.lukk.ascend.ai.mcp.weather.config;

import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpRequest;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.web.client.RestClientException;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;

public class ResponseSizeLimitingInterceptor implements ClientHttpRequestInterceptor {

    public static final int DEFAULT_MAX_BYTES = 256 * 1024;

    private final int maxBytes;

    public ResponseSizeLimitingInterceptor() {
        this(DEFAULT_MAX_BYTES);
    }

    public ResponseSizeLimitingInterceptor(int maxBytes) {
        this.maxBytes = maxBytes;
    }

    @Override
    public ClientHttpResponse intercept(HttpRequest request, byte[] body, ClientHttpRequestExecution execution)
            throws IOException {
        ClientHttpResponse response = execution.execute(request, body);
        long advertised = response.getHeaders().getContentLength();

        if (advertised > maxBytes) {
            throw new RestClientException(
                    "Upstream response too large: advertised " + advertised + " bytes (max " + maxBytes + ")");
        }

        byte[] buffered = response.getBody().readNBytes(maxBytes + 1);

        if (buffered.length > maxBytes) {
            throw new RestClientException(
                    "Upstream response too large: read past " + maxBytes + " bytes");
        }

        return new BufferedClientHttpResponse(response, buffered);
    }

    private record BufferedClientHttpResponse(ClientHttpResponse delegate, byte[] buffered) implements ClientHttpResponse {

        @Override
        public HttpStatusCode getStatusCode() throws IOException {
            return delegate.getStatusCode();
        }

        @Override
        public String getStatusText() throws IOException {
            return delegate.getStatusText();
        }

        @Override
        public void close() {
            delegate.close();
        }

        @Override
        public InputStream getBody() {
            return new ByteArrayInputStream(buffered);
        }

        @Override
        public HttpHeaders getHeaders() {
            return delegate.getHeaders();
        }
    }
}
