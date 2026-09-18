package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.config.mcp.FilteredToolCallbackProvider;
import com.lukk.ascend.ai.agent.config.mcp.McpClientEntry;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatus;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry;
import com.lukk.ascend.ai.agent.service.provider.ChatModelResolver;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.mcp.AsyncMcpToolCallbackProvider;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Collection;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Verifies MCP startup-tolerance behaviour: the Spring context must refresh successfully
 * and keep serving prompts when every configured MCP server is unreachable.
 *
 * <p>This test cannot be run without Docker (it extends {@link TestcontainersBase}). Run
 * via {@code ./gradlew integrationTest}.
 *
 * <p>MCP is kept disabled at the {@code TestcontainersBase} layer to avoid interfering
 * with other ITs. This class overrides that flag and redirects every connection URL
 * configured in {@code application.yaml} (ascend-audio-scribe, ascend-weather-mcp, ascend-web-hunter) to
 * an unreachable port, leaving the broader chat-model providers disabled as usual. Those
 * connection keys are redirected rather than replaced with a fictional one because
 * {@code Map<String, ConnectionParameters>} property binding merges by key across
 * property sources, so a dynamically-added key would sit alongside, not instead of, the
 * three real ones. Redirecting all three keeps the test deterministic regardless of
 * whether the real ascend-audio-scribe/ascend-weather-mcp/ascend-web-hunter services happen to be reachable
 * on the host running the test, which is exactly what this test verifies: every configured
 * MCP client ends up FAILED and the context still starts.
 */
@AutoConfigureMockMvc
class McpStartupToleranceIT extends TestcontainersBase {

    private static final String UNREACHABLE_URL = "http://localhost:1";
    private static final Map<String, String> CONFIGURED_CONNECTIONS = Map.of(
            "ascend-audio-scribe", UNREACHABLE_URL,
            "ascend-weather-mcp", UNREACHABLE_URL,
            "ascend-web-hunter", UNREACHABLE_URL);

    @DynamicPropertySource
    static void overrideMcpProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.ai.mcp.client.enabled", () -> true);
        registry.add("spring.ai.mcp.client.initialized", () -> false);
        registry.add("app.mcp.startup.init-timeout", () -> "1s");
        registry.add("app.rag.enabled", () -> false);
        CONFIGURED_CONNECTIONS.forEach((name, url) ->
                registry.add("spring.ai.mcp.client.streamable-http.connections." + name + ".url", () -> url));
    }

    @MockitoBean
    ChatModelResolver chatModelResolver;

    @Autowired
    private ApplicationContext applicationContext;

    @Autowired
    private McpClientStatusRegistry statusRegistry;

    @Autowired
    private ToolCallbackProvider toolCallbackProvider;

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("Spring context refreshes successfully when the configured MCP server is unreachable")
    void contextRefreshes_WhenMcpServerUnreachable_DoesNotFail() {
        assertThat(applicationContext).isNotNull();
    }

    @Test
    @DisplayName("Registry records FAILED status for the unreachable MCP server")
    void registry_WhenMcpServerUnreachable_RecordsFailedStatus() {
        Collection<McpClientEntry> entries = statusRegistry.entries();

        assertThat(entries).isNotEmpty();
        assertThat(entries).allMatch(e -> e.status() == McpClientStatus.FAILED);
    }

    @Test
    @DisplayName("Registry keys every entry by the bare connection name and carries its configured URL")
    void registry_RealSpringAiWiring_HoldsConnectionNamesAndConfiguredUrls() {
        Collection<McpClientEntry> entries = statusRegistry.entries();

        assertThat(entries)
                .extracting(McpClientEntry::name)
                .containsExactlyInAnyOrderElementsOf(CONFIGURED_CONNECTIONS.keySet());
        assertThat(entries).allSatisfy(entry ->
                assertThat(entry.url()).isEqualTo(CONFIGURED_CONNECTIONS.get(entry.name())));
    }

    @Test
    @DisplayName("FilteredToolCallbackProvider returns empty callbacks when all MCP clients are FAILED")
    void toolCallbackProvider_WhenAllClientsFailed_ReturnsEmptyCallbacks() {
        ToolCallback[] callbacks = toolCallbackProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("The context holds no unfiltered MCP tool-callback provider that could bypass the status filter")
    void applicationContext_ToolCallbackProviderBeans_ContainOnlyTheFilteredWrapper() {
        Collection<ToolCallbackProvider> providers =
                applicationContext.getBeansOfType(ToolCallbackProvider.class).values();

        assertThat(providers).hasSize(1);
        assertThat(providers).allSatisfy(p -> assertThat(p).isInstanceOf(FilteredToolCallbackProvider.class));
        assertThat(applicationContext.getBeanNamesForType(SyncMcpToolCallbackProvider.class)).isEmpty();
        assertThat(applicationContext.getBeanNamesForType(AsyncMcpToolCallbackProvider.class)).isEmpty();
    }

    @Test
    @DisplayName("Prompt endpoint returns 200 while every configured MCP server is unreachable")
    void promptEndpoint_WhenAllMcpClientsFailed_Returns200() throws Exception {
        when(chatModelResolver.resolve(anyString())).thenReturn(new StubChatModel());

        mockMvc.perform(multipart("/api/v1/ai/prompt")
                        .param("prompt", "Say hello")
                        .param("provider", "lmstudio")
                        .param("embeddingProvider", "lmstudio"))
                .andExpect(status().isOk());
    }

    private static final class StubChatModel implements ChatModel {

        @Override
        public ChatResponse call(Prompt prompt) {
            return new ChatResponse(List.of(new Generation(new AssistantMessage("stubbed answer"))));
        }
    }
}
