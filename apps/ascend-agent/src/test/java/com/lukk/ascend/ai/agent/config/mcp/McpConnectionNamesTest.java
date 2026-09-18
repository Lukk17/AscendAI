package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class McpConnectionNamesTest {

    @Test
    @DisplayName("resolve prefers the client title, which Spring AI sets to the bare connection key")
    void resolve_TitlePresent_ReturnsTitle() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(
                new McpSchema.Implementation("AscendAI-Agent - ascend-audio-scribe", "ascend-audio-scribe", "0.0.1"));

        assertThat(McpConnectionNames.resolve(client)).isEqualTo("ascend-audio-scribe");
    }

    @Test
    @DisplayName("resolve falls back to the name when the title is blank")
    void resolve_BlankTitleWithName_ReturnsName() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(new McpSchema.Implementation("ascend-weather-mcp", "", "0.0.1"));

        assertThat(McpConnectionNames.resolve(client)).isEqualTo("ascend-weather-mcp");
    }

    @Test
    @DisplayName("resolve falls back to the name when the title is null")
    void resolve_NullTitleWithName_ReturnsName() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(new McpSchema.Implementation("ascend-weather-mcp", "0.0.1"));

        assertThat(McpConnectionNames.resolve(client)).isEqualTo("ascend-weather-mcp");
    }

    @Test
    @DisplayName("resolve gives two unnamed clients distinct, stable fallback names so they do not collapse")
    void resolve_UnnamedClients_ReturnDistinctStableNames() {
        McpSyncClient first = mock(McpSyncClient.class);
        McpSyncClient second = mock(McpSyncClient.class);
        when(first.getClientInfo()).thenReturn(null);
        when(second.getClientInfo()).thenReturn(null);

        String firstName = McpConnectionNames.resolve(first);
        String secondName = McpConnectionNames.resolve(second);

        assertThat(firstName).startsWith("unknown-");
        assertThat(secondName).startsWith("unknown-");
        assertThat(firstName).isNotEqualTo(secondName);
        assertThat(McpConnectionNames.resolve(first)).isEqualTo(firstName);
    }

    @Test
    @DisplayName("fallbackName matches what resolve produces for a client with no client info")
    void fallbackName_ClientWithoutInfo_MatchesResolveOutput() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(null);

        assertThat(McpConnectionNames.fallbackName(client)).isEqualTo(McpConnectionNames.resolve(client));
    }
}
