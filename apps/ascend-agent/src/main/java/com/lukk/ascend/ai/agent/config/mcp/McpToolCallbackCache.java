package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpToolCacheProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.mcp.McpToolsChangedEvent;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Function;

/**
 * Holds the last MCP tool listing for a short expiry, keyed on the set of servers the
 * {@link McpClientStatusRegistry} reports as connected. See ADR-010.
 *
 * <p>A listing is served only while the connected set, the invalidation generation and the
 * expiry all still match, so a server marked failed loses its tools on the very next call.
 * A listing during which the connected set changed, or an invalidation arrived, is returned
 * to its caller but never stored.
 */
@Component
@ConditionalOnProperty(prefix = "spring.ai.mcp.client", name = "enabled", havingValue = "true", matchIfMissing = true)
@Slf4j
public class McpToolCallbackCache {

    private final McpClientStatusRegistry registry;
    private final McpToolCacheProperties properties;
    private final Clock clock;
    private final AtomicLong invalidations = new AtomicLong();
    private volatile CachedListing cachedListing;

    public McpToolCallbackCache(McpClientStatusRegistry registry, McpToolCacheProperties properties, Clock clock) {
        this.registry = registry;
        this.properties = properties;
        this.clock = clock;
    }

    public ToolCallback[] getOrList(Function<Set<String>, ToolCallback[]> listConnectedServers) {
        Set<String> connectedNames = registry.connectedNames();
        long generation = invalidations.get();
        CachedListing cached = cachedListing;
        if (cached != null && cached.isServableFor(connectedNames, generation, clock.instant())) {
            return cached.toArray();
        }

        ToolCallback[] listed = listConnectedServers.apply(connectedNames);
        if (registry.connectedNames().equals(connectedNames)) {
            cachedListing = new CachedListing(Set.copyOf(connectedNames), List.of(listed),
                    generation, clock.instant().plus(properties.getTtl()));
        }

        return listed;
    }

    @EventListener
    public void onToolsChanged(McpToolsChangedEvent event) {
        log.info("MCP server '{}' reported a tools change, invalidating the cached tool listing",
                event.getConnectionName());
        invalidations.incrementAndGet();
        cachedListing = null;
    }

    private record CachedListing(Set<String> connectedNames, List<ToolCallback> callbacks,
                                 long generation, Instant expiresAt) {

        private boolean isServableFor(Set<String> currentConnectedNames, long currentGeneration, Instant now) {
            return generation == currentGeneration
                    && now.isBefore(expiresAt)
                    && connectedNames.equals(currentConnectedNames);
        }

        private ToolCallback[] toArray() {
            return callbacks.toArray(ToolCallback[]::new);
        }
    }
}
