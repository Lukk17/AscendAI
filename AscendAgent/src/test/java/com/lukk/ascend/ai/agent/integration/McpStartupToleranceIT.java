package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.config.mcp.McpClientStatus;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.util.Collection;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies MCP startup-tolerance behaviour: the Spring context must refresh successfully
 * when one configured MCP server is unreachable.
 *
 * <p>This test cannot be run without Docker (it extends {@link TestcontainersBase}). Run
 * via {@code ./gradlew integrationTest}.
 *
 * <p>MCP is kept disabled at the {@code TestcontainersBase} layer to avoid interfering
 * with other ITs. This class overrides that flag and adds two fake MCP connections: one
 * pointing at port 1 (always refused) to exercise the FAILED path, leaving the broader
 * chat-model providers disabled as usual. There is no running MCP server, so both
 * entries end up FAILED — which is exactly what this test verifies: context still starts.
 */
class McpStartupToleranceIT extends TestcontainersBase {

    @DynamicPropertySource
    static void overrideMcpProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.ai.mcp.client.enabled", () -> true);
        registry.add("spring.ai.mcp.client.initialized", () -> false);
        registry.add("app.mcp.startup.init-timeout", () -> "1s");
        registry.add("spring.ai.mcp.client.streamable-http.connections.test-server.url",
                () -> "http://localhost:1");
    }

    @Autowired
    private ApplicationContext applicationContext;

    @Autowired
    private McpClientStatusRegistry statusRegistry;

    @Autowired
    private ToolCallbackProvider toolCallbackProvider;

    @Test
    @DisplayName("Spring context refreshes successfully when the configured MCP server is unreachable")
    void contextRefreshes_WhenMcpServerUnreachable_DoesNotFail() {
        assertThat(applicationContext).isNotNull();
    }

    @Test
    @DisplayName("Registry records FAILED status for the unreachable MCP server")
    void registry_WhenMcpServerUnreachable_RecordsFailedStatus() {
        Collection<com.lukk.ascend.ai.agent.config.mcp.McpClientEntry> entries = statusRegistry.entries();

        assertThat(entries).isNotEmpty();
        assertThat(entries).allMatch(e -> e.status() == McpClientStatus.FAILED);
    }

    @Test
    @DisplayName("FilteredToolCallbackProvider returns empty callbacks when all MCP clients are FAILED")
    void toolCallbackProvider_WhenAllClientsFailed_ReturnsEmptyCallbacks() {
        org.springframework.ai.tool.ToolCallback[] callbacks = toolCallbackProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }
}
