package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpStartupProperties;
import io.modelcontextprotocol.client.McpSyncClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.mcp.McpToolNamePrefixGenerator;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.definition.DefaultToolDefinition;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;
import java.util.regex.Pattern;

/**
 * Exposes only the tool callbacks of the {@link McpSyncClient} instances the
 * {@link McpClientStatusRegistry} currently reports as {@link McpClientStatus#CONNECTED}.
 *
 * <p>Discovery of a stale session is recovered with one reconnect-and-retry cycle per client,
 * serialised per client; a client still failing afterwards is demoted to {@code FAILED}.
 * See ADR-008 for the rationale behind filtering by client rather than by callback.
 */
@Component
@Primary
@ConditionalOnProperty(prefix = "spring.ai.mcp.client", name = "enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class FilteredToolCallbackProvider implements ToolCallbackProvider {

    private final List<McpSyncClient> allClients;
    private final McpClientStatusRegistry registry;
    private final McpStartupProperties startupProperties;
    private final Map<String, ReconnectGate> reconnectGates = new ConcurrentHashMap<>();

    /** OpenAI and Anthropic require tool function names to match this pattern. */
    private static final Pattern ILLEGAL_TOOL_NAME_CHARS = Pattern.compile("[^a-zA-Z0-9_-]");

    public FilteredToolCallbackProvider(List<McpSyncClient> allClients,
                                        McpClientStatusRegistry registry,
                                        McpStartupProperties startupProperties) {
        this.allClients = allClients;
        this.registry = registry;
        this.startupProperties = startupProperties;
    }

    @Override
    public ToolCallback[] getToolCallbacks() {
        Set<String> connected = registry.connectedNames();
        List<McpSyncClient> connectedClients = allClients.stream()
                .filter(client -> connected.contains(McpConnectionNames.resolve(client)))
                .toList();

        if (connectedClients.isEmpty()) {
            log.debug("FilteredToolCallbackProvider: no connected MCP clients, returning empty tool set");
            return new ToolCallback[0];
        }

        List<ToolCallback> discovered = new ArrayList<>();
        for (McpSyncClient client : connectedClients) {
            discovered.addAll(discoverToolCallbacks(client));
        }

        ToolCallback[] sanitized = discovered.stream()
                .map(FilteredToolCallbackProvider::sanitizeName)
                .toArray(ToolCallback[]::new);
        return disambiguateCollisions(sanitized);
    }

    private List<ToolCallback> discoverToolCallbacks(McpSyncClient client) {
        String name = McpConnectionNames.resolve(client);
        ReconnectGate gate = reconnectGates.computeIfAbsent(name, key -> new ReconnectGate());
        long generationBeforeDiscovery = gate.generation().get();
        try {
            return listTools(client);
        } catch (RuntimeException firstFailure) {
            log.warn("MCP client '{}' tool discovery failed, attempting reconnect: {}",
                    name, firstFailure.getMessage());
            if (!reconnect(client, name, gate, generationBeforeDiscovery)) {
                return List.of();
            }
            try {
                return listTools(client);
            } catch (RuntimeException retryFailure) {
                log.warn("MCP client '{}' tool discovery still failing after reconnect, excluding its tools "
                                + "from this request: {}", name, retryFailure.getMessage());
                log.debug("MCP {} tool discovery failed after reconnect", name, retryFailure);
                registry.markFailed(name);

                return List.of();
            }
        }
    }

    private List<ToolCallback> listTools(McpSyncClient client) {
        SyncMcpToolCallbackProvider singleClientProvider = SyncMcpToolCallbackProvider.builder()
                .mcpClients(List.of(client))
                .toolNamePrefixGenerator(McpToolNamePrefixGenerator.noPrefix())
                .build();

        return List.of(singleClientProvider.getToolCallbacks());
    }

    private boolean reconnect(McpSyncClient client, String name, ReconnectGate gate, long generationBeforeDiscovery) {
        gate.lock().lock();
        try {
            if (gate.generation().get() != generationBeforeDiscovery) {
                log.debug("MCP {} already reconnected by a concurrent request, skipping duplicate initialise", name);

                return true;
            }

            Mono.fromRunnable(client::initialize)
                    .subscribeOn(Schedulers.boundedElastic())
                    .timeout(startupProperties.getInitTimeout())
                    .block();
            gate.generation().incrementAndGet();

            return true;
        } catch (RuntimeException e) {
            log.warn("MCP client '{}' reconnect failed within {}: {}",
                    name, startupProperties.getInitTimeout(), e.getMessage());
            log.debug("MCP {} reconnect failed", name, e);
            registry.markFailed(name);

            return false;
        } finally {
            gate.lock().unlock();
        }
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

    private record ReconnectGate(ReentrantLock lock, AtomicLong generation) {

        private ReconnectGate() {
            this(new ReentrantLock(), new AtomicLong());
        }
    }
}
