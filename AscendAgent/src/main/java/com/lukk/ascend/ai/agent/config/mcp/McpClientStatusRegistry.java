package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.Collection;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

@Component
@Slf4j
public class McpClientStatusRegistry {

    private final ConcurrentHashMap<String, McpClientEntry> entries = new ConcurrentHashMap<>();

    public void record(String name, String url, McpClientStatus status, Throwable cause) {
        entries.put(name, new McpClientEntry(name, url, status));
        if (cause != null) {
            log.debug("MCP {} init failed: {}", name, cause.getMessage(), cause);
        }
    }

    public Collection<McpClientEntry> entries() {
        return entries.values();
    }

    public Set<String> connectedNames() {
        return entries.values().stream()
                .filter(e -> e.status() == McpClientStatus.CONNECTED)
                .map(McpClientEntry::name)
                .collect(Collectors.toSet());
    }

    static String resolveConnectionName(McpSyncClient client) {
        var clientInfo = client.getClientInfo();
        if (clientInfo != null && clientInfo.title() != null && !clientInfo.title().isBlank()) {
            return clientInfo.title();
        }
        if (clientInfo != null && clientInfo.name() != null && !clientInfo.name().isBlank()) {
            return clientInfo.name();
        }
        return "unknown-" + Integer.toHexString(System.identityHashCode(client));
    }
}
