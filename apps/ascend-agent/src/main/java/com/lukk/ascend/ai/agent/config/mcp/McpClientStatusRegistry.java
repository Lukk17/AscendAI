package com.lukk.ascend.ai.agent.config.mcp;

import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

@Component
public class McpClientStatusRegistry {

    private static final String UNKNOWN_URL = "unknown";

    private final ConcurrentHashMap<String, McpClientEntry> entries = new ConcurrentHashMap<>();

    public void record(String name, String url, McpClientStatus status) {
        entries.put(name, new McpClientEntry(name, url, status));
    }

    /**
     * Demotes an already-recorded client to {@code FAILED}, keeping the URL it was recorded with.
     */
    public void markFailed(String name) {
        entries.compute(name, (key, existing) -> new McpClientEntry(
                key,
                existing != null ? existing.url() : UNKNOWN_URL,
                McpClientStatus.FAILED));
    }

    public Collection<McpClientEntry> entries() {
        return List.copyOf(entries.values());
    }

    public Set<String> connectedNames() {
        return entries.values().stream()
                .filter(e -> e.status() == McpClientStatus.CONNECTED)
                .map(McpClientEntry::name)
                .collect(Collectors.toSet());
    }
}
