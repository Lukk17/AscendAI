package com.lukk.ascend.ai.mcp.weather.config;

import org.springframework.http.HttpRequest;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.lang.NonNull;
import org.springframework.web.client.RestClientException;

import java.io.IOException;
import java.io.InputStream;

public class ResponseSizeLimitingInterceptor implements ClientHttpRequestInterceptor {

    public static final int DEFAULT_MAX_BYTES = 256 * 1024;
    private static final int READ_CHUNK_BYTES = 8192;

    private final int maxBytes;

    public ResponseSizeLimitingInterceptor() {
        this(DEFAULT_MAX_BYTES);
    }

    public ResponseSizeLimitingInterceptor(int maxBytes) {
        this.maxBytes = maxBytes;
    }

    @Override
    @NonNull
    public ClientHttpResponse intercept(@NonNull HttpRequest request,
                                        @NonNull byte[] body,
                                        @NonNull ClientHttpRequestExecution execution) throws IOException {
        ClientHttpResponse response = execution.execute(request, body);
        long advertised = response.getHeaders().getContentLength();

        if (advertised > maxBytes) {
            response.close();

            throw new RestClientException(
                    "Upstream response too large: advertised " + advertised + " bytes (max " + maxBytes + ")");
        }

        try (InputStream in = response.getBody()) {
            int total = 0;
            byte[] chunk = new byte[READ_CHUNK_BYTES];
            int read;
            while ((read = in.read(chunk)) != -1) {
                total += read;
                if (total > maxBytes) {
                    response.close();

                    throw new RestClientException(
                            "Upstream response too large: read past " + maxBytes + " bytes");
                }
            }
        }

        return response;
    }
}
