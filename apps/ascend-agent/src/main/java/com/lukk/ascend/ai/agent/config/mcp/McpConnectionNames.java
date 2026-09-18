package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;

/**
 * Resolves the bare connection key Spring AI stores on a client's {@code clientInfo().title()}.
 */
final class McpConnectionNames {

    private McpConnectionNames() {
    }

    static String resolve(McpSyncClient client) {
        McpSchema.Implementation clientInfo = client.getClientInfo();
        if (clientInfo != null && clientInfo.title() != null && !clientInfo.title().isBlank()) {
            return clientInfo.title();
        }
        if (clientInfo != null && clientInfo.name() != null && !clientInfo.name().isBlank()) {
            return clientInfo.name();
        }

        return fallbackName(client);
    }

    static String fallbackName(McpSyncClient client) {
        return "unknown-" + Integer.toHexString(System.identityHashCode(client));
    }
}
