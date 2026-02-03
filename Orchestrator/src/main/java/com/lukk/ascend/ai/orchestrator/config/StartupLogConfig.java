package com.lukk.ascend.ai.orchestrator.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.core.env.Environment;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.s3.S3Client;

import javax.sql.DataSource;
import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.util.Optional;
import java.util.stream.Collectors;

@Component
public class StartupLogConfig implements ApplicationListener<ApplicationReadyEvent> {

    private static final Logger log = LoggerFactory.getLogger(StartupLogConfig.class);
    private final Environment env;
    private final DataSource dataSource;
    private final StringRedisTemplate redisTemplate;
    private final S3Client s3Client;
    private final ObjectProvider<ToolCallbackProvider> toolCallbackProvider;

    public StartupLogConfig(Environment env, DataSource dataSource, StringRedisTemplate redisTemplate,
            S3Client s3Client, ObjectProvider<ToolCallbackProvider> toolCallbackProvider) {
        this.env = env;
        this.dataSource = dataSource;
        this.redisTemplate = redisTemplate;
        this.s3Client = s3Client;
        this.toolCallbackProvider = toolCallbackProvider;
    }

    @Override
    public void onApplicationEvent(ApplicationReadyEvent event) {
        String serverPort = env.getProperty("local.server.port", env.getProperty("server.port"));
        String contextPath = env.getProperty("server.servlet.context-path", "");
        String hostAddress = "localhost";
        try {
            hostAddress = InetAddress.getLocalHost().getHostAddress();
        } catch (UnknownHostException e) {
            log.warn("The host name could not be determined, using `localhost` as fallback");
        }

        String protocol = "http";
        if (env.getProperty("server.ssl.key-store") != null) {
            protocol = "https";
        }

        String appName = env.getProperty("spring.application.name", "AscendAI Orchestrator");
        String mainPromptUrl = String.format("%s://localhost:%s%s/prompt", protocol, serverPort, contextPath);
        String aiBaseUrl = env.getProperty("spring.ai.openai.base-url", "unknown");
        String aiChatModel = env.getProperty("spring.ai.openai.chat.options.model", "unknown");

        String[] profiles = env.getActiveProfiles();
        String activeProfiles = (profiles.length == 0) ? "default" : String.join(", ", profiles);

        String dbStatus = checkDatabase();
        String redisStatus = checkRedis();
        String s3Status = checkS3();
        String mcpStatus = checkMcpTools();

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
                "\tLocal:      \t{}://localhost:{}{}\n" +
                "\tExternal:   \t{}://{}:{}{}\n" +
                "\tAI:         \t{}\n" +
                "\n" +
                "\tProfile(s): \t{}\n" +
                "\tAI model:   \t{}\n" +
                "\n" +
                "\tActionable Status:\n" +
                "\t- Postgres:    \t{}\n" +
                "\t- Redis:       \t{}\n" +
                "\t- S3 Ingested: \t{}\n" +
                "\t- MCP Tools:   \t{}\n" +
                "\n" +
                "\tMAIN PROMPT ENDPOINT:\n" +
                "\tPOST        \t{}\n" +
                "----------------------------------------------------------",
                appName,
                protocol, serverPort, contextPath,
                protocol, hostAddress, serverPort, contextPath,
                aiBaseUrl,
                activeProfiles,
                aiChatModel,
                dbStatus,
                redisStatus,
                s3Status,
                mcpStatus,
                mainPromptUrl);
    }

    private String checkDatabase() {
        try (Connection connection = dataSource.getConnection()) {
            DatabaseMetaData metaData = connection.getMetaData();

            return Optional.ofNullable(metaData.getURL())
                    .map(url -> url.replace("jdbc:", ""))
                    .map(URI::create)
                    .map(uri -> String.format("[Connected] Address: %s:%d, DB Name: %s",
                            uri.getHost(),
                            uri.getPort(),
                            Optional.ofNullable(uri.getPath())
                                    .map(this::sanitizeDatabaseName)
                                    .orElse("Unknown")))
                    .orElse("[Connected] Address: Unknown, DB Name: Unknown");

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
            return String.format("[Connected] Host: %s:%s", host, port);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkS3() {
        try {
            String bucket = env.getProperty("app.s3.bucket", "knowledge-base");
            long count = s3Client.listObjects(b -> b.bucket(bucket)).contents().size();
            return String.format("[Connected] Bucket: %s | Ingested Files: %d", bucket, count);
        } catch (Exception e) {
            return "[FAILED] " + e.getMessage();
        }
    }

    private String checkMcpTools() {
        try {
            ToolCallbackProvider provider = toolCallbackProvider.getIfAvailable();
            if (provider == null) {
                return "[Warning] No ToolCallbackProvider found.";
            }
            ToolCallback[] tools = provider.getToolCallbacks();
            if (tools == null || tools.length == 0) {
                return "[Connected] No tools registered (List is empty).";
            }

            String toolNames = java.util.Arrays.stream(tools)
                    .map(t -> t.getToolDefinition().name())
                    .collect(Collectors.joining(", "));
            return String.format("[Connected] Tools: [%s]", toolNames);
        } catch (Exception e) {
            return "[FAILED] Error retrieving tools: " + e.getMessage();
        }
    }
}
