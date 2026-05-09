package com.lukk.ascend.ai.agent.config;


import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
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
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import software.amazon.awssdk.services.s3.S3Client;

import javax.sql.DataSource;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

@Component
@Slf4j
public class StartupLogConfig {

    private final Environment env;
    private final DataSource dataSource;
    private final StringRedisTemplate redisTemplate;
    private final S3Client s3Client;
    private final ObjectProvider<ToolCallbackProvider> toolCallbackProvider;
    private final AiProviderProperties aiProviderProperties;
    private final EmbeddingProviderProperties embeddingProviderProperties;
    private final SemanticMemoryProperties semanticMemoryProperties;
    private final ObjectProvider<QdrantClient> qdrantClientProvider;

    public StartupLogConfig(Environment env, DataSource dataSource, StringRedisTemplate redisTemplate,
                            S3Client s3Client, ObjectProvider<ToolCallbackProvider> toolCallbackProvider,
                            AiProviderProperties aiProviderProperties,
                            EmbeddingProviderProperties embeddingProviderProperties,
                            SemanticMemoryProperties semanticMemoryProperties,
                            ObjectProvider<QdrantClient> qdrantClientProvider) {
        this.env = env;
        this.dataSource = dataSource;
        this.redisTemplate = redisTemplate;
        this.s3Client = s3Client;
        this.toolCallbackProvider = toolCallbackProvider;
        this.aiProviderProperties = aiProviderProperties;
        this.embeddingProviderProperties = embeddingProviderProperties;
        this.semanticMemoryProperties = semanticMemoryProperties;
        this.qdrantClientProvider = qdrantClientProvider;
    }

    @EventListener
    public void onReadinessChange(AvailabilityChangeEvent<ReadinessState> event) {
        if (event.getState() != ReadinessState.ACCEPTING_TRAFFIC) {
            return;
        }
        String serverPort = env.getProperty("local.server.port", env.getProperty("server.port"));
        String contextPath = env.getProperty("server.servlet.context-path", "");
        String hostAddress = "localhost";
        try {
            hostAddress = InetAddress.getLocalHost().getHostAddress();
        } catch (UnknownHostException e) {
            log.warn("The host name could not be determined, using `localhost` as fallback");
        }

        String protocol = env.getProperty("server.ssl.key-store") != null ? "https" : "http";
        String appName = env.getProperty("spring.application.name", "AscendAI Agent");
        String mainPromptUrl = String.format("%s://localhost:%s%s/api/v1/ai/prompt", protocol, serverPort, contextPath);

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        log.info("\n" +
                        "    _    ___  ___ ___ _  _ ___      _  ___ \n" +
                        "   /_\\  / __|/ __/ __| \\| |   \\    /_\\|_ _|\n" +
                        "  / _ \\ \\__ \\ (__| _|| .` | |) |  / _ \\| | \n" +
                        " /_/ \\_\\|___/\\___|___|_|\\_|___/  /_/ \\_\\___|\n" +
                        "\n" +
                        "----------------------------------------------------------\n" +
                        "\tApplication '{}' is running!\n" +
                        "\n" +
                        "\tAccess URLs:\n" +
                        "\t  Local:    \t{}://localhost:{}{}\n" +
                        "\t  External: \t{}://{}:{}{}\n" +
                        "\n" +
                        "\tProfile(s): \t{}\n" +
                        "\n" +
                        "\tChat providers (default = {}):\n" +
                        "{}\n" +
                        "\tEmbedding providers (default = {}):\n" +
                        "{}\n" +
                        "\tInfrastructure:\n" +
                        "\t  Postgres:        \t{}\n" +
                        "\t  Redis:           \t{}\n" +
                        "\t  Qdrant:          \t{}\n" +
                        "\t  S3 Ingested:     \t{}\n" +
                        "\t  AscendMemory:    \t{}\n" +
                        "\n" +
                        "\tMCP Tools:         \t{}\n" +
                        "\n" +
                        "\tMAIN PROMPT ENDPOINT:\n" +
                        "\t  POST           \t{}\n" +
                        "----------------------------------------------------------",
                appName,
                protocol, serverPort, contextPath,
                protocol, hostAddress, serverPort, contextPath,
                activeProfiles,
                aiProviderProperties.getDefaultProvider(),
                formatChatProviders(),
                embeddingProviderProperties.getDefaultProvider(),
                formatEmbeddingProviders(),
                checkDatabase(),
                checkRedis(),
                checkQdrant(),
                checkS3(),
                checkAscendMemory(),
                checkMcpTools(),
                mainPromptUrl);
    }

    private String formatChatProviders() {
        Map<String, AiProviderProperties.ProviderConfig> providers = aiProviderProperties.getProviders();
        if (providers == null || providers.isEmpty()) {
            return "\t  (none configured)";
        }
        return providers.entrySet().stream()
                .map(e -> String.format("\t  - %-10s\ttype=%s\tmodel=%s", e.getKey(), e.getValue().getType(), e.getValue().getModel()))
                .collect(Collectors.joining("\n"));
    }

    private String formatEmbeddingProviders() {
        Map<String, EmbeddingProviderProperties.EmbeddingConfig> providers = embeddingProviderProperties.getProviders();
        if (providers == null || providers.isEmpty()) {
            return "\t  (none configured)";
        }
        return providers.entrySet().stream()
                .map(e -> String.format("\t  - %-10s\tdims=%d\tmodel=%s\tcollection=ascendai-%d",
                        e.getKey(), e.getValue().getDimensions(), e.getValue().getModel(), e.getValue().getDimensions()))
                .collect(Collectors.joining("\n"));
    }

    private String checkDatabase() {
        try (Connection connection = dataSource.getConnection()) {
            DatabaseMetaData metaData = connection.getMetaData();
            return Optional.ofNullable(metaData.getURL())
                    .map(url -> url.replace("jdbc:", ""))
                    .map(URI::create)
                    .map(uri -> String.format("[Connected] %s:%d / %s",
                            uri.getHost(), uri.getPort(),
                            Optional.ofNullable(uri.getPath()).map(this::sanitizeDatabaseName).orElse("Unknown")))
                    .orElse("[Connected] Unknown");
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String sanitizeDatabaseName(String path) {
        return path.startsWith("/") ? path.substring(1) : path;
    }

    private String checkRedis() {
        try {
            redisTemplate.getConnectionFactory().getConnection().ping();
            String host = env.getProperty("spring.data.redis.host");
            String port = env.getProperty("spring.data.redis.port");
            return String.format("[Connected] %s:%s", host, port);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkQdrant() {
        try {
            QdrantClient client = qdrantClientProvider.getIfAvailable();
            if (client == null) {
                return "[Warning] no QdrantClient bean";
            }
            int count = client.listCollectionsAsync().get().size();
            String host = env.getProperty("spring.ai.vectorstore.qdrant.host", "unknown");
            String port = env.getProperty("spring.ai.vectorstore.qdrant.port", "6334");
            return String.format("[Connected] %s:%s | Collections: %d", host, port, count);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkS3() {
        try {
            String bucket = env.getProperty("app.s3.bucket", "knowledge-base");
            long count = s3Client.listObjects(b -> b.bucket(bucket)).contents().size();
            return String.format("[Connected] %s | Files: %d", bucket, count);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkAscendMemory() {
        if (!semanticMemoryProperties.isEnabled()) {
            return "[Disabled] (app.memory.semantic.enabled=false)";
        }
        try {
            String baseUrl = semanticMemoryProperties.getBaseUrl();
            int status = RestClient.create().get().uri(baseUrl + "/health").retrieve().toBodilessEntity().getStatusCode().value();
            return status == 200 ? String.format("[Connected] %s", baseUrl)
                    : String.format("[Warning] %s (status=%d)", baseUrl, status);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkMcpTools() {
        try {
            ToolCallbackProvider provider = toolCallbackProvider.getIfAvailable();
            if (provider == null) {
                return "[Warning] No ToolCallbackProvider found";
            }
            ToolCallback[] tools = provider.getToolCallbacks();
            if (tools == null || tools.length == 0) {
                return "[Connected] no tools registered";
            }
            String toolNames = java.util.Arrays.stream(tools)
                    .map(t -> t.getToolDefinition().name())
                    .collect(Collectors.joining(", "));
            return String.format("[Connected] %d tools: [%s]", tools.length, toolNames);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }
}
