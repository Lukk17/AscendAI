package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpStartupProperties;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import io.modelcontextprotocol.spec.McpTransportSessionNotFoundException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.DefaultToolDefinition;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
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

    private McpStartupProperties startupProperties;

    private FilteredToolCallbackProvider provider;

    @BeforeEach
    void setUp() {
        McpSchema.Implementation connectedInfo = new McpSchema.Implementation("AscendAI-Agent - ascend-audio-scribe", "ascend-audio-scribe", "0.0.1");
        McpSchema.Implementation failedInfo = new McpSchema.Implementation("AscendAI-Agent - ascend-weather-mcp", "ascend-weather-mcp", "0.0.1");
        when(connectedClient.getClientInfo()).thenReturn(connectedInfo);
        when(failedClient.getClientInfo()).thenReturn(failedInfo);

        startupProperties = new McpStartupProperties();
        provider = new FilteredToolCallbackProvider(List.of(connectedClient, failedClient), registry, startupProperties);
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
        FilteredToolCallbackProvider emptyProvider = new FilteredToolCallbackProvider(List.of(), registry, startupProperties);
        when(registry.connectedNames()).thenReturn(Set.of("ascend-audio-scribe"));

        ToolCallback[] callbacks = emptyProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("getToolCallbacks filters out client whose name is not in connected set")
    void getToolCallbacks_OnlyConnectedClientNamesFiltered_FailedClientExcluded() {
        when(registry.connectedNames()).thenReturn(Set.of("ascend-audio-scribe"));

        FilteredToolCallbackProvider singleProvider = new FilteredToolCallbackProvider(
                List.of(failedClient), registry, startupProperties);

        ToolCallback[] callbacks = singleProvider.getToolCallbacks();

        assertThat(callbacks).isEmpty();
    }

    @Test
    @DisplayName("getToolCallbacks reconnects and retries when a CONNECTED client's session has gone stale")
    void getToolCallbacks_StaleSessionOnFirstDiscovery_ReconnectsAndReturnsToolsFromRetry() {
        when(registry.connectedNames()).thenReturn(Set.of("ascend-audio-scribe"));
        when(connectedClient.listTools())
                .thenThrow(new McpTransportSessionNotFoundException("stale-session-id"))
                .thenReturn(new McpSchema.ListToolsResult(List.of(stubTool("transcribe")), null));

        FilteredToolCallbackProvider singleProvider = new FilteredToolCallbackProvider(
                List.of(connectedClient), registry, startupProperties);

        ToolCallback[] callbacks = singleProvider.getToolCallbacks();

        assertThat(callbacks).hasSize(1);
        assertThat(callbacks[0].getToolDefinition().name()).isEqualTo("transcribe");
        verify(connectedClient, times(1)).initialize();
        verify(connectedClient, times(2)).listTools();
    }

    @Test
    @DisplayName("getToolCallbacks excludes a client still failing after reconnect but keeps other clients' tools")
    void getToolCallbacks_DiscoveryStillFailsAfterReconnect_ExcludesThatClientKeepsOthers() {
        when(registry.connectedNames()).thenReturn(Set.of("ascend-audio-scribe", "ascend-weather-mcp"));
        when(connectedClient.listTools())
                .thenReturn(new McpSchema.ListToolsResult(List.of(stubTool("transcribe")), null));
        when(failedClient.listTools())
                .thenThrow(new McpTransportSessionNotFoundException("stale-session-id"));

        ToolCallback[] callbacks = provider.getToolCallbacks();

        assertThat(callbacks).hasSize(1);
        assertThat(callbacks[0].getToolDefinition().name()).isEqualTo("transcribe");
        verify(failedClient, times(1)).initialize();
        verify(failedClient, times(2)).listTools();
    }

    @Test
    @DisplayName("sanitizeName replaces dots with underscores and delegates call() to original")
    void sanitizeName_illegalCharsInName_replacedWithUnderscore_callDelegatesToOriginal() {
        String expectedOutput = "original-result";
        ToolCallback original = stubCallback("a.b", expectedOutput);

        ToolCallback result = FilteredToolCallbackProvider.sanitizeName(original);

        assertThat(result.getToolDefinition().name()).isEqualTo("a_b");
        assertThat(result.call("{}")).isEqualTo(expectedOutput);
    }

    @Test
    @DisplayName("sanitizeName returns original instance when name has no illegal characters")
    void sanitizeName_legalName_returnsSameInstance() {
        ToolCallback original = stubCallback("search_web", "result");

        ToolCallback result = FilteredToolCallbackProvider.sanitizeName(original);

        assertThat(result).isSameAs(original);
    }

    @Test
    @DisplayName("disambiguateCollisions gives both 'search.web' and 'search_web' distinct names after sanitizing")
    void disambiguateCollisions_twoCallbacksWithSameSanitizedName_bothSurviveWithDistinctNames() {
        String outputDot = "result-from-search.web";
        String outputUnderscore = "result-from-search_web";
        ToolCallback cb1 = FilteredToolCallbackProvider.sanitizeName(stubCallback("search.web", outputDot));
        ToolCallback cb2 = FilteredToolCallbackProvider.sanitizeName(stubCallback("search_web", outputUnderscore));

        ToolCallback[] result = FilteredToolCallbackProvider.disambiguateCollisions(new ToolCallback[]{cb1, cb2});

        assertThat(result).hasSize(2);
        String name0 = result[0].getToolDefinition().name();
        String name1 = result[1].getToolDefinition().name();
        assertThat(name0).isNotEqualTo(name1);
        assertThat(result[0].call("{}")).isEqualTo(outputDot);
        assertThat(result[1].call("{}")).isEqualTo(outputUnderscore);
    }

    @Test
    @DisplayName("disambiguateCollisions appends _2 to the second occurrence of a colliding name")
    void disambiguateCollisions_collision_secondOccurrenceSuffixedWith_2() {
        ToolCallback cb1 = stubCallback("a_b", "first");
        ToolCallback cb2 = stubCallback("a_b", "second");

        ToolCallback[] result = FilteredToolCallbackProvider.disambiguateCollisions(new ToolCallback[]{cb1, cb2});

        assertThat(result[0].getToolDefinition().name()).isEqualTo("a_b");
        assertThat(result[1].getToolDefinition().name()).isEqualTo("a_b_2");
        assertThat(result[0].call("{}")).isEqualTo("first");
        assertThat(result[1].call("{}")).isEqualTo("second");
    }

    private static ToolCallback stubCallback(String name, String callOutput) {
        ToolDefinition def = DefaultToolDefinition.builder()
                .name(name)
                .description("stub tool " + name)
                .inputSchema("{}")
                .build();
        return new ToolCallback() {
            @Override
            public ToolDefinition getToolDefinition() {
                return def;
            }

            @Override
            public ToolMetadata getToolMetadata() {
                return mock(ToolMetadata.class);
            }

            @Override
            public String call(String toolInput) {
                return callOutput;
            }

            @Override
            public String call(String toolInput, ToolContext toolContext) {
                return callOutput;
            }
        };
    }

    private static McpSchema.Tool stubTool(String name) {
        McpSchema.JsonSchema inputSchema = new McpSchema.JsonSchema("object", Map.of(), List.of(), false, null, null);
        return McpSchema.Tool.builder()
                .name(name)
                .description("stub MCP tool " + name)
                .inputSchema(inputSchema)
                .build();
    }
}
