package com.lukk.ai.orchestrator.config;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.boot.autoconfigure.web.client.RestClientBuilderConfigurer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.ClientHttpRequestFactory;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;

@Configuration
public class AppConfig {

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder, ToolCallbackProvider toolCallbackProvider) {
        return builder
                .defaultSystem("You are a helpful and friendly assistant. Answer the user's questions clearly and concisely.")
                .defaultToolCallbacks(toolCallbackProvider)
                .build();

    }

    // This bean is a workaround for a known issue where Java's modern HTTP/2 client
    // fails to communicate properly with the LM Studio server, causing requests to hang.
    // By forcing the RestClient to use the older, more stable HTTP/1.1 protocol,
    // we ensure reliable communication.
    @Bean
    public RestClient.Builder restClientBuilder(RestClientBuilderConfigurer configurer) {
        // Create an HttpClient instance that is explicitly forced to use HTTP/1.1
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .build();

        // Create a Spring RequestFactory that uses our custom HttpClient
        ClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(httpClient);

        // Apply the default Spring Boot configurations and then add our custom request factory
        return configurer.configure(RestClient.builder())
                .requestFactory(requestFactory);
    }
}
