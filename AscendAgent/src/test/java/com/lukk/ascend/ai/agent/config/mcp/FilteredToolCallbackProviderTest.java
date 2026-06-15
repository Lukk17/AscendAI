package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.tool.ToolCallback;

import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class FilteredToolCallbackProviderTest {

    @Mock
    private McpClientStatusRegistry registry;

    @Mock
    private McpSyncClient connectedClient;

    @Mock
    private McpSyncClient failedClient;

    private FilteredToolCallbackProvider provider;

    @BeforeEach
    void setUp() {
        McpSchema.Implementation connectedInfo = new McpSchema.Implementation("AscendAI-Agent - audioscribe", "audioscribe", "0.0.1");
        McpSchema.Implementation failedInfo = new McpSchema.Implementation("AscendAI-Agent - weather", "weather", "0.0.1");
        when(connectedClient.getClientInfo()).thenReturn(connectedInfo);
        when(failedClient.getClientInfo()).thenReturn(failedInfo);

        provider = new FilteredToolCallbackProvider(List.of(connectedClient, failedClient), registry);
    }

    @Test
    @DisplayName("getToolCallbacks returns empty array when all clients are FAILED")
    void getToolCallbacks_AllClientsFailed_ReturnsEmptyArray() {
        when(registry.connectedNames()).thenReturn(Set.of());

        ToolCallback[] callbacks = provider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("getToolCallbacks returns empty array when registry has no entries")
    void getToolCallbacks_RegistryEmpty_ReturnsEmptyArray() {
        when(registry.connectedNames()).thenReturn(Set.of());

        ToolCallback[] callbacks = provider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("getToolCallbacks with no clients returns empty array")
    void getToolCallbacks_NoClients_ReturnsEmptyArray() {
        FilteredToolCallbackProvider emptyProvider = new FilteredToolCallbackProvider(List.of(), registry);
        when(registry.connectedNames()).thenReturn(Set.of("audioscribe"));

        ToolCallback[] callbacks = emptyProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("getToolCallbacks filters out client whose name is not in connected set")
    void getToolCallbacks_OnlyConnectedClientNamesFiltered_FailedClientExcluded() {
        when(registry.connectedNames()).thenReturn(Set.of("audioscribe"));

        FilteredToolCallbackProvider singleProvider = new FilteredToolCallbackProvider(
                List.of(failedClient), registry);

        ToolCallback[] callbacks = singleProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }
}
