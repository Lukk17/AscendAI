package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpStartupProperties;
import io.modelcontextprotocol.client.McpSyncClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.mcp.client.common.autoconfigure.properties.McpStreamableHttpClientProperties;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.util.List;
import java.util.Map;

@Component
@ConditionalOnProperty(prefix = "spring.ai.mcp.client", name = "enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class McpClientStartupInitializer {

    private static final String UNKNOWN_URL = "unknown";

    private final List<McpSyncClient> mcpSyncClients;
    private final McpClientStatusRegistry registry;
    private final McpStartupProperties startupProperties;
    private final McpStreamableHttpClientProperties streamableHttpProperties;

    public McpClientStartupInitializer(List<McpSyncClient> mcpSyncClients,
                                       McpClientStatusRegistry registry,
                                       McpStartupProperties startupProperties,
                                       McpStreamableHttpClientProperties streamableHttpProperties) {
        this.mcpSyncClients = mcpSyncClients;
        this.registry = registry;
        this.startupProperties = startupProperties;
        this.streamableHttpProperties = streamableHttpProperties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void initialize() {
        Duration timeout = startupProperties.getInitTimeout();
        Map<String, McpStreamableHttpClientProperties.ConnectionParameters> connections =
                streamableHttpProperties.getConnections();

        int connected = 0;
        for (McpSyncClient client : mcpSyncClients) {
            if (initializeClient(client, connections, timeout)) {
                connected++;
            }
        }

        int total = mcpSyncClients.size();
        if (total > 0) {
            log.info("MCP startup complete: {}/{} clients connected", connected, total);
        }
    }

    private boolean initializeClient(McpSyncClient client,
                                     Map<String, McpStreamableHttpClientProperties.ConnectionParameters> connections,
                                     Duration timeout) {
        String connectionName = McpConnectionNames.fallbackName(client);
        String url = UNKNOWN_URL;
        try {
            connectionName = McpConnectionNames.resolve(client);
            url = resolveUrl(connectionName, connections);

            Mono.fromRunnable(client::initialize)
                    .subscribeOn(Schedulers.boundedElastic())
                    .timeout(timeout)
                    .block();

            registry.record(connectionName, url, McpClientStatus.CONNECTED);
            log.info("MCP client '{}' at {} connected", connectionName, url);

            return true;
        } catch (Exception e) {
            Throwable cause = unwrap(e);
            registry.record(connectionName, url, McpClientStatus.FAILED);
            log.warn("MCP client '{}' at {} failed to initialise within {}: {}",
                    connectionName, url, timeout, cause.getMessage());
            log.debug("MCP {} init failed", connectionName, cause);

            return false;
        }
    }

    private String resolveUrl(String connectionName,
                              Map<String, McpStreamableHttpClientProperties.ConnectionParameters> connections) {
        if (connections == null) {
            return UNKNOWN_URL;
        }
        McpStreamableHttpClientProperties.ConnectionParameters params = connections.get(connectionName);
        if (params == null) {
            return UNKNOWN_URL;
        }

        return params.url() != null ? params.url() : UNKNOWN_URL;
    }

    private Throwable unwrap(Throwable t) {
        if (t.getCause() != null) {
            return t.getCause();
        }

        return t;
    }
}
