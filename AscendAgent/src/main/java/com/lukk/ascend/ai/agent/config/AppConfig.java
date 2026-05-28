package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.config.properties.VectorStoreProperties;
import com.lukk.ascend.ai.agent.config.properties.VisionCapabilityProperties;
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
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.S3Configuration;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

import java.net.URI;
import java.net.http.HttpClient;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

@Configuration
@EnableConfigurationProperties({VectorStoreProperties.class, VisionCapabilityProperties.class})
// CGLIB proxies (proxyTargetClass=true) — PersistentChatMemory implements
// ChatMemory but is injected as the concrete type by ChatHistoryService for
// the 4-arg add() overload that's not on the ChatMemory interface. JDK
// proxies (the default) would only expose the interface and break wiring.
@EnableAsync(proxyTargetClass = true)
@Slf4j
public class AppConfig {

    @Bean
    public Executor taskExecutor() {
        return Executors.newVirtualThreadPerTaskExecutor();
    }

    @Bean
    public TransactionTemplate transactionTemplate(PlatformTransactionManager txManager) {
        return new TransactionTemplate(txManager);
    }

    @Value("${app.system-prompt}")
    private String systemPrompt;

    @Value("${app.ingestion.connect-timeout}")
    private int connectTimeout;

    @Value("${app.ingestion.read-timeout}")
    private int readTimeout;

    @Value("${app.s3.endpoint}")
    private String s3Endpoint;

    @Value("${app.s3.public-endpoint:${app.s3.endpoint}}")
    private String s3PublicEndpoint;

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
     * Presigner uses the PUBLIC endpoint, so the resulting URLs are reachable from
     * the caller's network (host browser / curl), not just from inside the docker
     * network where the agent runs.
     */
    @Bean
    public S3Presigner s3Presigner() {
        return S3Presigner.builder()
                .endpointOverride(URI.create(s3PublicEndpoint))
                .region(Region.US_EAST_1)
                .credentialsProvider(StaticCredentialsProvider.create(
                        AwsBasicCredentials.create(s3AccessKey, s3SecretKey)))
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
     * @param dataSource The generic DataSource (autoconfigured by Spring Boot).
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
