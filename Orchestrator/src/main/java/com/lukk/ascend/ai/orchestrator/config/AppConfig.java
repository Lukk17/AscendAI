package com.lukk.ascend.ai.orchestrator.config;

import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
import io.qdrant.client.QdrantClient;
import io.qdrant.client.grpc.Collections;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.autoconfigure.web.client.RestClientBuilderConfigurer;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.integration.jdbc.metadata.JdbcMetadataStore;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import java.net.URI;

import java.net.http.HttpClient;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

@Configuration
@EnableConfigurationProperties(VectorStoreProperties.class)
@Slf4j
public class AppConfig {

    @Bean
    public Executor taskExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Value("${app.system-prompt}")
    private String systemPrompt;

    @Value("${app.ingestion.connect-timeout}")
    private int connectTimeout;

    @Value("${app.ingestion.read-timeout}")
    private int readTimeout;

    @Value("${app.s3.endpoint}")
    private String s3Endpoint;

    @Value("${app.s3.access-key}")
    private String s3AccessKey;

    @Value("${app.s3.secret-key}")
    private String s3SecretKey;

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

    @Bean
    public RestClient restClient(RestClient.Builder builder) {
        return builder.build();
    }

    @Bean("ingestionRestClient")
    public RestClient ingestionRestClient() {
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeout);
        factory.setReadTimeout(readTimeout);
        return RestClient.builder()
                .requestFactory(factory)
                .build();
    }

    @Bean
    public S3Client s3Client() {
        return S3Client.builder()
                .endpointOverride(URI.create(s3Endpoint))
                // MinIO requires a region, usually ignores it but needs one
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider
                        .create(
                                AwsBasicCredentials
                                        .create(s3AccessKey, s3SecretKey)))
                .serviceConfiguration(S3Configuration.builder()
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
        return new JdbcMetadataStore(dataSource);
    }

    @Bean
    public CommandLineRunner initVectorStore(QdrantClient qdrantClient,
                                             VectorStoreProperties vectorStoreProperties) {
        return args -> {
            try {
                List<String> existingCollections = qdrantClient.listCollectionsAsync().get();
                vectorStoreProperties.getCollections()
                        .forEach(config -> createCollectionIfAbsent(qdrantClient,
                                existingCollections, config));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.error("Failed to fetch existing collections", e);
            } catch (ExecutionException e) {
                log.error("Failed to fetch existing collections", e);
            }
        };
    }

    private void createCollectionIfAbsent(QdrantClient qdrantClient, List<String> existingCollections,
                                          VectorStoreProperties.CollectionConfig config) {
        if (existingCollections.contains(config.getName())) {
            log.info("[AppConfig] Collection '{}' already exists.", config.getName());
            return;
        }

        log.info("[AppConfig] Collection '{}' not found. Creating with size {}...", config.getName(),
                config.getSize());
        try {
            qdrantClient.createCollectionAsync(
                            config.getName(),
                            Collections.VectorParams.newBuilder()
                                    .setSize(config.getSize())
                                    .setDistance(Collections.Distance.Cosine)
                                    .build())
                    .get();
            log.info("[AppConfig] Collection '{}' created successfully.", config.getName());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            log.error("[AppConfig] Interrupted while creating collection '{}'", config.getName(), e);
        } catch (ExecutionException e) {
            log.error("[AppConfig] Failed to create collection '{}'", config.getName(), e);
        }
    }
}
