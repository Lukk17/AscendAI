package com.lukk.ascend.ai.orchestrator.config;

import io.qdrant.client.QdrantClient;
import io.qdrant.client.grpc.Collections;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.web.client.RestClientBuilderConfigurer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

@Configuration
@Slf4j
public class AppConfig {

    @Bean
    public Executor taskExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Value("${app.ingestion.system-prompt}")
    private String systemPrompt;

    @Bean
    public ChatClient chatClient(ChatClient.Builder builder, SyncMcpToolCallbackProvider toolCallbackProvider) {
        var tools = toolCallbackProvider.getToolCallbacks();
        log.debug("Found {} tools from MCP provider.", tools.length);

        for (var tool : tools) {
            log.debug("Tool found: {}", tool.getToolDefinition().name());
        }

        return builder
                .defaultSystem(systemPrompt)
                .defaultToolCallbacks(tools)
                .build();

    }

    /**
     * Configures the RestClient.Builder.
     * <p>
     * This method forces the underlying HttpClient to use HTTP/1.1 instead of
     * HTTP/2.
     * This is required to solve compatibility issues with the LM Studio server,
     * which can hang when receiving HTTP/2 requests from the modern Java 21
     * HttpClient.
     * </p>
     *
     * @param configurer The Spring Boot configurer to apply default customizations.
     * @return A configured RestClient.Builder instance using HTTP/1.1.
     */
    @Bean
    public RestClient.Builder restClientBuilder(RestClientBuilderConfigurer configurer) {
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .build();

        return configurer.configure(RestClient.builder())
                .requestFactory(new JdkClientHttpRequestFactory(httpClient));
    }

    @Value("${app.s3.endpoint}")
    private String s3Endpoint;

    @Value("${app.s3.access-key}")
    private String s3AccessKey;

    @Value("${app.s3.secret-key}")
    private String s3SecretKey;

    @Bean
    public software.amazon.awssdk.services.s3.S3Client s3Client() {
        return software.amazon.awssdk.services.s3.S3Client.builder()
                .endpointOverride(java.net.URI.create(s3Endpoint))
                // MinIO requires a region, usually ignores it but needs one
                .region(software.amazon.awssdk.regions.Region.US_EAST_1)
                .credentialsProvider(software.amazon.awssdk.auth.credentials.StaticCredentialsProvider
                        .create(
                                software.amazon.awssdk.auth.credentials.AwsBasicCredentials
                                        .create(s3AccessKey, s3SecretKey)))
                .serviceConfiguration(software.amazon.awssdk.services.s3.S3Configuration.builder()
                        .pathStyleAccessEnabled(true)
                        .build())
                .build();
    }

    /**
     * Creates a JDBC-backed metadata store for persistent file tracking.
     * <p>
     * This ensures files are processed only once, even across application restarts.
     * </p>
     *
     * @param dataSource The generic DataSource (auto-configured by Spring Boot).
     * @return A ConcurrentMetadataStore backed by the database.
     */
    @Bean
    public ConcurrentMetadataStore metadataStore(
            javax.sql.DataSource dataSource) {
        return new org.springframework.integration.jdbc.metadata.JdbcMetadataStore(dataSource);
    }

    @Bean
    public org.springframework.boot.CommandLineRunner initVectorStore(QdrantClient qdrantClient) {
        return args -> {
            String collectionName = "ascendai";
            try {
                qdrantClient.listCollectionsAsync().get().stream()
                        .filter(c -> c.equals(collectionName))
                        .findFirst()
                        .ifPresentOrElse(
                                c -> log.info("Collection '{}' already exists.",
                                        collectionName),
                                () -> {
                                    log.info("Collection '{}' not found. Creating...",
                                            collectionName);
                                    try {
                                        qdrantClient.createCollectionAsync(
                                                        collectionName,
                                                        Collections.VectorParams
                                                                .newBuilder()
                                                                .setSize(768) // Nomic
                                                                // Embed
                                                                // Text
                                                                // v1.5
                                                                // dimensions
                                                                .setDistance(Collections.Distance.Cosine)
                                                                .build())
                                                .get();
                                        log.info("Collection '{}' created successfully.",
                                                collectionName);
                                    } catch (Exception e) {
                                        log.error("Failed to create collection '{}'",
                                                collectionName, e);
                                    }
                                });
            } catch (Exception e) {
                log.error("Failed to check collection '{}'", collectionName, e);
            }
        };
    }
}
