package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.definition.DefaultToolDefinition;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

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

    /** OpenAI and Anthropic require tool function names to match this pattern. */
    private static final Pattern ILLEGAL_TOOL_NAME_CHARS = Pattern.compile("[^a-zA-Z0-9_-]");

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

        ToolCallback[] sanitized = Arrays.stream(new SyncMcpToolCallbackProvider(connectedClients).getToolCallbacks())
                .map(FilteredToolCallbackProvider::sanitizeName)
                .toArray(ToolCallback[]::new);
        return disambiguateCollisions(sanitized);
    }

    /**
     * OpenAI and Anthropic reject tool function names that contain characters outside
     * {@code ^[a-zA-Z0-9_-]+$} (e.g. an MCP server exposing a dotted name). Replace any
     * illegal character with {@code _} so the tool list is accepted. The LLM sees the
     * sanitized name and Spring AI routes the call back through this wrapper to the
     * original MCP tool, so behavior is unchanged.
     */
    static ToolCallback sanitizeName(ToolCallback original) {
        ToolDefinition def = original.getToolDefinition();
        String cleaned = ILLEGAL_TOOL_NAME_CHARS.matcher(def.name()).replaceAll("_");
        if (cleaned.equals(def.name())) {
            return original;
        }
        log.debug("Sanitized MCP tool name '{}' -> '{}' for provider compatibility", def.name(), cleaned);
        ToolDefinition sanitized = DefaultToolDefinition.builder()
                .name(cleaned)
                .description(def.description())
                .inputSchema(def.inputSchema())
                .build();
        return new ToolCallback() {
            @Override
            public ToolDefinition getToolDefinition() {
                return sanitized;
            }

            @Override
            public ToolMetadata getToolMetadata() {
                return original.getToolMetadata();
            }

            @Override
            public String call(String toolInput) {
                return original.call(toolInput);
            }

            @Override
            public String call(String toolInput, ToolContext toolContext) {
                return original.call(toolInput, toolContext);
            }
        };
    }

    static ToolCallback[] disambiguateCollisions(ToolCallback[] callbacks) {
        Map<String, Integer> seenCounts = new HashMap<>();
        ToolCallback[] result = new ToolCallback[callbacks.length];
        for (int i = 0; i < callbacks.length; i++) {
            ToolCallback cb = callbacks[i];
            String name = cb.getToolDefinition().name();
            int count = seenCounts.merge(name, 1, Integer::sum);
            if (count == 1) {
                result[i] = cb;
            } else {
                String disambiguated = name + "_" + count;
                log.warn("MCP tool name collision: '{}' appeared {} times; renaming occurrence to '{}'",
                        name, count, disambiguated);
                ToolDefinition def = cb.getToolDefinition();
                ToolDefinition renamed = DefaultToolDefinition.builder()
                        .name(disambiguated)
                        .description(def.description())
                        .inputSchema(def.inputSchema())
                        .build();
                result[i] = new ToolCallback() {
                    @Override
                    public ToolDefinition getToolDefinition() {
                        return renamed;
                    }

                    @Override
                    public ToolMetadata getToolMetadata() {
                        return cb.getToolMetadata();
                    }

                    @Override
                    public String call(String toolInput) {
                        return cb.call(toolInput);
                    }

                    @Override
                    public String call(String toolInput, ToolContext toolContext) {
                        return cb.call(toolInput, toolContext);
                    }
                };
            }
        }
        return result;
    }

    private String resolveConnectionName(McpSyncClient client) {
        return McpClientStatusRegistry.resolveConnectionName(client);
    }
}
