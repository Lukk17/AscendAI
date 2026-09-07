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
 * with other ITs. This class overrides that flag and redirects every connection URL
 * configured in {@code application.yaml} (audioscribe, weather, ascend-web-hunter) to
 * an unreachable port, leaving the broader chat-model providers disabled as usual. Those
 * connection keys are redirected rather than replaced with a fictional one because
 * {@code Map<String, ConnectionParameters>} property binding merges by key across
 * property sources, so a dynamically-added key would sit alongside, not instead of, the
 * three real ones. Redirecting all three keeps the test deterministic regardless of
 * whether the real AudioScribe/WeatherMCP/ascend-web-hunter services happen to be reachable
 * on the host running the test, which is exactly what this test verifies: every configured
 * MCP client ends up FAILED and the context still starts.
 */
class McpStartupToleranceIT extends TestcontainersBase {

    @DynamicPropertySource
    static void overrideMcpProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.ai.mcp.client.enabled", () -> true);
        registry.add("spring.ai.mcp.client.initialized", () -> false);
        registry.add("app.mcp.startup.init-timeout", () -> "1s");
        registry.add("spring.ai.mcp.client.streamable-http.connections.audioscribe.url",
                () -> "http://localhost:1");
        registry.add("spring.ai.mcp.client.streamable-http.connections.weather.url",
                () -> "http://localhost:1");
        registry.add("spring.ai.mcp.client.streamable-http.connections.ascend-web-hunter.url",
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
