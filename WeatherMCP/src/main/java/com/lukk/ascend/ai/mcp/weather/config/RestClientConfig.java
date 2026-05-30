package com.lukk.ascend.ai.mcp.weather.config;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.time.Duration;

@Configuration
public class RestClientConfig {

    public static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(4);
    public static final Duration READ_TIMEOUT = Duration.ofSeconds(8);
    public static final String OPEN_METEO_BEAN_NAME = "openMeteoRestClient";

    @Bean
    @Qualifier(OPEN_METEO_BEAN_NAME)
    public RestClient openMeteoRestClient() {
        return RestClient.builder()
                .requestFactory(buildRequestFactory())
                .requestInterceptor(new ResponseSizeLimitingInterceptor())
                .build();
    }

    private static JdkClientHttpRequestFactory buildRequestFactory() {
        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(CONNECT_TIMEOUT)
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
        factory.setReadTimeout(READ_TIMEOUT);

        return factory;
    }
}
