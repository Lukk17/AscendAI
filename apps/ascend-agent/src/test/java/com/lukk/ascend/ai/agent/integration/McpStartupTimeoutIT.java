package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.config.mcp.McpClientEntry;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatus;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.IOException;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies the per-client init timeout against a server that completes the TCP handshake and
 * then never answers the MCP {@code initialize} request. Without the timeout this client would
 * hold the startup loop for the full {@code spring.ai.mcp.client.request-timeout}, so reaching
 * any assertion at all already proves the timeout fired; the assertions then pin the recorded
 * state and the resulting tool set.
 */
class McpStartupTimeoutIT extends TestcontainersBase {

    private static final String STALLING_CONNECTION = "ascend-weather-mcp";
    private static final String UNREACHABLE_URL = "http://localhost:1";

    private static final List<Socket> ACCEPTED_CONNECTIONS = new CopyOnWriteArrayList<>();
    private static final ServerSocket SILENT_SERVER = openSilentServer();

    @DynamicPropertySource
    static void overrideMcpProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.ai.mcp.client.enabled", () -> true);
        registry.add("spring.ai.mcp.client.initialized", () -> false);
        registry.add("app.mcp.startup.init-timeout", () -> "200ms");
        registry.add("app.rag.enabled", () -> false);
        registry.add("spring.ai.mcp.client.streamable-http.connections.ascend-audio-scribe.url",
                () -> UNREACHABLE_URL);
        registry.add("spring.ai.mcp.client.streamable-http.connections.ascend-web-hunter.url",
                () -> UNREACHABLE_URL);
        registry.add("spring.ai.mcp.client.streamable-http.connections." + STALLING_CONNECTION + ".url",
                McpStartupTimeoutIT::silentServerUrl);
    }

    @Autowired
    private McpClientStatusRegistry statusRegistry;

    @Autowired
    private ToolCallbackProvider toolCallbackProvider;

    @Test
    @DisplayName("A server that accepts the connection but never answers the handshake is recorded FAILED")
    void registry_WhenHandshakeStalls_RecordsFailedForThatConnection() {
        // when
        McpClientEntry stalling = statusRegistry.entries().stream()
                .filter(entry -> entry.name().equals(STALLING_CONNECTION))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No registry entry recorded for " + STALLING_CONNECTION));

        // then
        assertThat(ACCEPTED_CONNECTIONS)
                .as("the stand-in server must have accepted the TCP connection, otherwise this is a "
                        + "connection-refused scenario rather than a stalled handshake")
                .isNotEmpty();
        assertThat(stalling.status()).isEqualTo(McpClientStatus.FAILED);
        assertThat(stalling.url()).isEqualTo(silentServerUrl());
        assertThat(statusRegistry.connectedNames()).isEmpty();
    }

    @Test
    @DisplayName("A stalled client advertises no tools")
    void toolCallbackProvider_WhenHandshakeStalled_ReturnsEmptyCallbacks() {
        // when
        ToolCallback[] callbacks = toolCallbackProvider.getToolCallbacks();

        // then
        assertThat(callbacks).isEmpty();
    }

    private static String silentServerUrl() {
        return "http://127.0.0.1:" + SILENT_SERVER.getLocalPort();
    }

    private static ServerSocket openSilentServer() {
        try {
            ServerSocket serverSocket = new ServerSocket(0, 50, InetAddress.getLoopbackAddress());
            Thread accepting = new Thread(() -> holdConnections(serverSocket), "mcp-silent-server");
            accepting.setDaemon(true);
            accepting.start();

            return serverSocket;
        } catch (IOException e) {
            throw new IllegalStateException("Could not open the silent MCP stand-in server", e);
        }
    }

    private static void holdConnections(ServerSocket serverSocket) {
        while (!serverSocket.isClosed()) {
            try {
                ACCEPTED_CONNECTIONS.add(serverSocket.accept());
            } catch (IOException e) {
                return;
            }
        }
    }
}
