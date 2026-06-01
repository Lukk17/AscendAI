package com.lukk.ascend.ai.agent.config;


import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import io.qdrant.client.QdrantClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.context.event.EventListener;
import org.springframework.core.env.Environment;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;

import javax.sql.DataSource;
import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Component
@Slf4j
public class StartupLogConfig {

    private static final String BANNER_RESOURCE = "banner.txt";

    private static final String DIVIDER = "----------------------------------------------------------";

    private static final Duration PROBE_TIMEOUT = Duration.ofSeconds(2);

    private final Environment env;
    private final DataSource dataSource;
    private final StringRedisTemplate redisTemplate;
    private final S3Client s3Client;
    private final ObjectProvider<ToolCallbackProvider> toolCallbackProvider;
    private final AiProviderProperties aiProviderProperties;
    private final EmbeddingProviderProperties embeddingProviderProperties;
    private final SemanticMemoryProperties semanticMemoryProperties;
    private final ChatHistoryProperties chatHistoryProperties;
    private final ChatHistoryCompactionProperties compactionProperties;
    private final ObjectProvider<QdrantClient> qdrantClientProvider;

    public StartupLogConfig(Environment env, DataSource dataSource, StringRedisTemplate redisTemplate,
                            S3Client s3Client, ObjectProvider<ToolCallbackProvider> toolCallbackProvider,
                            AiProviderProperties aiProviderProperties,
                            EmbeddingProviderProperties embeddingProviderProperties,
                            SemanticMemoryProperties semanticMemoryProperties,
                            ChatHistoryProperties chatHistoryProperties,
                            ChatHistoryCompactionProperties compactionProperties,
                            ObjectProvider<QdrantClient> qdrantClientProvider) {
        this.env = env;
        this.dataSource = dataSource;
        this.redisTemplate = redisTemplate;
        this.s3Client = s3Client;
        this.toolCallbackProvider = toolCallbackProvider;
        this.aiProviderProperties = aiProviderProperties;
        this.embeddingProviderProperties = embeddingProviderProperties;
        this.semanticMemoryProperties = semanticMemoryProperties;
        this.chatHistoryProperties = chatHistoryProperties;
        this.compactionProperties = compactionProperties;
        this.qdrantClientProvider = qdrantClientProvider;
    }

    @EventListener
    public void onReadinessChange(AvailabilityChangeEvent<ReadinessState> event) {
        if (event.getState() != ReadinessState.ACCEPTING_TRAFFIC) {
            return;
        }
        String port = env.getProperty("local.server.port", env.getProperty("server.port", "9917"));
        String contextPath = env.getProperty("server.servlet.context-path", "");
        String protocol = env.getProperty("server.ssl.key-store") != null ? "https" : "http";
        String hostAddress = resolveHostAddress();
        String appName = env.getProperty("spring.application.name", "ascend-ai-agent");

        String localUrl = String.format("%s://localhost:%s%s", protocol, port, contextPath);
        String hostnameUrl = String.format("%s://%s:%s%s", protocol, hostAddress, port, contextPath);
        String promptEndpoint = localUrl + "/api/v1/ai/prompt";

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        List<String> lines = new ArrayList<>();
        lines.add("");
        lines.add(loadBanner());
        lines.add(DIVIDER);
        lines.add("    Application '" + appName + "' is running!");
        lines.add("");
        lines.add("    Access URLs:");
        lines.add("      Local:     " + localUrl);
        lines.add("      Hostname:  " + hostnameUrl);
        lines.add("");
        lines.add("    Profile(s): " + activeProfiles);
        lines.add("");
        lines.add("    Database:");
        lines.add("      Postgres:  " + checkDatabase());
        lines.add("");
        lines.add("    External services:");
        lines.add("      Redis:        " + checkRedis());
        lines.add("      Qdrant:       " + checkQdrant());
        lines.add("      S3 (MinIO):   " + checkS3());
        lines.add("      AscendMemory: " + checkAscendMemory());
        lines.add("");
        lines.add("    Actuator:");
        lines.add("      Health:     " + localUrl + "/actuator/health");
        lines.add("      Liveness:   " + localUrl + "/actuator/health/liveness");
        lines.add("      Readiness:  " + localUrl + "/actuator/health/readiness");
        lines.add("");
        lines.add("    API documentation:");
        lines.add("      OpenAPI:    " + localUrl + "/v3/api-docs");
        lines.add("      Swagger UI: " + localUrl + "/swagger-ui/index.html");
        lines.add("");
        lines.add("    Observability:");
        lines.add("      Logging:    console pattern with [AscendAI] tag (logging.pattern.console)");
        lines.add("");
        lines.add("    Chat providers (default = " + aiProviderProperties.getDefaultProvider() + "):");
        lines.add(formatChatProviders());
        lines.add("");
        lines.add("    Embedding providers (default = " + embeddingProviderProperties.getDefaultProvider() + "):");
        lines.add(formatEmbeddingProviders());
        lines.add("");
        lines.add("    Chat history: " + formatChatHistoryToggles());
        lines.add("    Compaction:   " + formatCompactionState());
        lines.add("");
        lines.add("    MCP tools:    " + checkMcpTools());
        lines.add("");
        lines.add("    MAIN PROMPT ENDPOINT:");
        lines.add("      POST  " + promptEndpoint);
        lines.add(DIVIDER);

        log.info("\n{}", String.join("\n", lines));
    }

    private String loadBanner() {
        ClassPathResource resource = new ClassPathResource(BANNER_RESOURCE);

        try (var in = resource.getInputStream()) {
            String raw = new String(in.readAllBytes(), StandardCharsets.UTF_8);

            return Arrays.stream(raw.split("\\R"))
                    .filter(line -> !line.contains("${"))
                    .filter(line -> !line.isBlank())
                    .collect(Collectors.joining("\n"));

        } catch (IOException e) {
            log.debug("Could not load {} from classpath; banner will be omitted", BANNER_RESOURCE, e);

            return "";
        }
    }

    private String resolveHostAddress() {
        try {
            return InetAddress.getLocalHost().getHostName();
        } catch (UnknownHostException e) {
            log.debug("Could not resolve host name; using localhost fallback", e);
            return "localhost";
        }
    }

    private String formatChatProviders() {
        Map<String, AiProviderProperties.ProviderConfig> providers = aiProviderProperties.getProviders();
        if (providers == null || providers.isEmpty()) {
            return "      (none configured)";
        }
        return providers.entrySet().stream()
                .map(e -> String.format("      - %-10s type=%s model=%s",
                        e.getKey(), e.getValue().getType(), e.getValue().getModel()))
                .collect(Collectors.joining("\n"));
    }

    private String formatEmbeddingProviders() {
        Map<String, EmbeddingProviderProperties.EmbeddingConfig> providers = embeddingProviderProperties.getProviders();
        if (providers == null || providers.isEmpty()) {
            return "      (none configured)";
        }
        return providers.entrySet().stream()
                .map(e -> String.format("      - %-10s dims=%d model=%s collection=ascendai-%d",
                        e.getKey(), e.getValue().getDimensions(), e.getValue().getModel(), e.getValue().getDimensions()))
                .collect(Collectors.joining("\n"));
    }

    private String checkDatabase() {
        try (Connection connection = dataSource.getConnection()) {
            DatabaseMetaData metaData = connection.getMetaData();
            String url = Optional.ofNullable(metaData.getURL())
                    .map(u -> u.replace("jdbc:", ""))
                    .orElse("unknown");
            return url + " [Connected]";
        } catch (Exception e) {
            log.debug("Postgres probe failed", e);
            String url = env.getProperty("spring.datasource.url", "unknown").replace("jdbc:", "");
            return url + " [FAILED]";
        }
    }

    private String checkRedis() {
        String host = env.getProperty("spring.data.redis.host", "unknown");
        String port = env.getProperty("spring.data.redis.port", "6379");
        String url = String.format("redis://%s:%s", host, port);

        var connectionFactory = redisTemplate.getConnectionFactory();
        if (connectionFactory == null) {
            return url + " [Warning (no connection factory)]";
        }

        try (var connection = connectionFactory.getConnection()) {
            connection.ping();

            return url + " [Connected]";

        } catch (Exception e) {
            log.debug("Redis probe failed", e);

            return url + " [FAILED]";
        }
    }

    private String checkQdrant() {
        String host = env.getProperty("spring.ai.vectorstore.qdrant.host", "unknown");
        String port = env.getProperty("spring.ai.vectorstore.qdrant.port", "6334");
        String url = String.format("%s:%s", host, port);
        try {
            QdrantClient client = qdrantClientProvider.getIfAvailable();
            if (client == null) {
                return url + " [Warning (no client bean)]";
            }
            int count = client.listCollectionsAsync().get(PROBE_TIMEOUT.toMillis(), TimeUnit.MILLISECONDS).size();
            return url + " [Connected] (collections: " + count + ")";
        } catch (Exception e) {
            log.debug("Qdrant probe failed", e);
            return url + " [FAILED]";
        }
    }

    private String checkS3() {
        String bucket = env.getProperty("app.s3.bucket", "knowledge-base");
        String endpoint = env.getProperty("app.s3.endpoint", "unknown");
        String url = String.format("%s/%s", endpoint, bucket);
        try {
            long count = s3Client.listObjects(b -> b.bucket(bucket)).contents().size();
            return url + " [Connected] (objects: " + count + ")";
        } catch (Exception e) {
            log.debug("S3 probe failed", e);
            return url + " [FAILED]";
        }
    }

    private String checkAscendMemory() {
        String baseUrl = semanticMemoryProperties.getBaseUrl();
        if (!semanticMemoryProperties.isEnabled()) {
            return baseUrl + " [Disabled]";
        }
        try {
            SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
            factory.setConnectTimeout((int) PROBE_TIMEOUT.toMillis());
            factory.setReadTimeout((int) PROBE_TIMEOUT.toMillis());
            int status = RestClient.builder()
                    .requestFactory(factory)
                    .build()
                    .get()
                    .uri(baseUrl + "/health")
                    .retrieve()
                    .toBodilessEntity()
                    .getStatusCode()
                    .value();
            if (status == 200) {
                return baseUrl + " [Connected]";
            }
            return baseUrl + String.format(" [Warning (status=%d)]", status);
        } catch (Exception e) {
            log.debug("AscendMemory probe failed", e);
            return baseUrl + " [FAILED]";
        }
    }

    private String formatChatHistoryToggles() {
        String redis = chatHistoryProperties.getRedis().isEnabled() ? "[Enabled]" : "[Disabled]";
        String postgres = chatHistoryProperties.getPostgres().isEnabled() ? "[Enabled]" : "[Disabled]";
        return String.format("Redis %s, Postgres %s", redis, postgres);
    }

    private String formatCompactionState() {
        if (!compactionProperties.isEnabled()) {
            return "[Disabled]";
        }
        String defaults = compactionProperties.getProviderDefaults().entrySet().stream()
                .map(e -> e.getKey() + "=" + e.getValue())
                .collect(Collectors.joining(", "));
        return String.format("[Enabled] (trigger: %d turns / %.0f%% context, keep: %d turns, defaults: %s)",
                compactionProperties.getTurnTrigger(),
                compactionProperties.getTokenTriggerFraction() * 100,
                compactionProperties.getKeepRecentTurns(),
                defaults);
    }

    private String checkMcpTools() {
        try {
            ToolCallbackProvider provider = toolCallbackProvider.getIfAvailable();
            if (provider == null) {
                return "[Warning (no ToolCallbackProvider)]";
            }
            ToolCallback[] tools = provider.getToolCallbacks();
            if (tools.length == 0) {
                return "[Connected] no tools registered";
            }
            String toolNames = Arrays.stream(tools)
                    .map(t -> t.getToolDefinition().name())
                    .collect(Collectors.joining(", "));
            return String.format("[Connected] %d tools: [%s]", tools.length, toolNames);
        } catch (Exception e) {
            log.debug("MCP tool listing failed", e);
            return "[FAILED]";
        }
    }
}
