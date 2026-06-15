package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Set;

/**
 * Wraps the full list of {@link McpSyncClient} instances and exposes only the tool
 * callbacks from clients that are currently in {@link McpClientStatus#CONNECTED} state.
 *
 * <p>At {@link #getToolCallbacks()} time this builds a fresh {@link SyncMcpToolCallbackProvider}
 * over only the CONNECTED clients, so the LLM never receives a tool definition that would
 * route to a FAILED client. The client-list filter approach is used rather than post-hoc
 * callback filtering to avoid fragile callback→client reverse lookups; see ADR-008.
 */
@Component
@Primary
@ConditionalOnProperty(prefix = "spring.ai.mcp.client", name = "enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class FilteredToolCallbackProvider implements ToolCallbackProvider {

    private final List<McpSyncClient> allClients;
    private final McpClientStatusRegistry registry;

    public FilteredToolCallbackProvider(List<McpSyncClient> allClients,
                                        McpClientStatusRegistry registry) {
        this.allClients = allClients;
        this.registry = registry;
    }

    @Override
    public ToolCallback[] getToolCallbacks() {
        Set<String> connected = registry.connectedNames();
        List<McpSyncClient> connectedClients = allClients.stream()
                .filter(client -> connected.contains(resolveConnectionName(client)))
                .toList();

        if (connectedClients.isEmpty()) {
            log.debug("FilteredToolCallbackProvider: no connected MCP clients, returning empty tool set");
            return new ToolCallback[0];
        }

        return new SyncMcpToolCallbackProvider(connectedClients).getToolCallbacks();
    }

    private String resolveConnectionName(McpSyncClient client) {
        var clientInfo = client.getClientInfo();
        if (clientInfo != null && clientInfo.title() != null && !clientInfo.title().isBlank()) {
            return clientInfo.title();
        }
        if (clientInfo != null && clientInfo.name() != null) {
            return clientInfo.name();
        }
        return "unknown";
    }
}
