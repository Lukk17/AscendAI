package com.lukk.ascend.ai.agent.config.mcp;

import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class McpClientStatusRegistryTest {

    private McpClientStatusRegistry registry;

    @BeforeEach
    void setUp() {
        registry = new McpClientStatusRegistry();
    }

    @Test
    @DisplayName("entries returns empty collection when nothing is recorded")
    void entries_WhenEmpty_ReturnsEmptyCollection() {
        assertThat(registry.entries()).isEmpty();
    }

    @Test
    @DisplayName("connectedNames returns empty set when nothing is recorded")
    void connectedNames_WhenEmpty_ReturnsEmptySet() {
        assertThat(registry.connectedNames()).isEmpty();
    }

    @Test
    @DisplayName("record persists a CONNECTED entry that appears in entries and connectedNames")
    void record_Connected_AppearsInEntriesAndConnectedNames() {
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED, null);

        assertThat(registry.entries()).hasSize(1);
        McpClientEntry entry = registry.entries().iterator().next();
        assertThat(entry.name()).isEqualTo("ascend-audio-scribe");
        assertThat(entry.url()).isEqualTo("http://localhost:7017");
        assertThat(entry.status()).isEqualTo(McpClientStatus.CONNECTED);

        assertThat(registry.connectedNames()).containsExactly("ascend-audio-scribe");
    }

    @Test
    @DisplayName("record persists a FAILED entry that does NOT appear in connectedNames")
    void record_Failed_DoesNotAppearInConnectedNames() {
        registry.record("weather", "http://localhost:9998", McpClientStatus.FAILED, new RuntimeException("refused"));

        assertThat(registry.entries()).hasSize(1);
        assertThat(registry.connectedNames()).isEmpty();
    }

    @Test
    @DisplayName("connectedNames returns only CONNECTED entries when registry has mixed states")
    void connectedNames_MixedStates_ReturnsOnlyConnected() {
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED, null);
        registry.record("weather", "http://localhost:9998", McpClientStatus.FAILED, new RuntimeException("refused"));
        registry.record("ascend-web-hunter", "http://localhost:7021", McpClientStatus.CONNECTED, null);

        Set<String> connected = registry.connectedNames();

        assertThat(connected).containsExactlyInAnyOrder("ascend-audio-scribe", "ascend-web-hunter");
        assertThat(connected).doesNotContain("weather");
    }

    @Test
    @DisplayName("record with null cause does not throw")
    void record_NullCause_DoesNotThrow() {
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED, null);

        assertThat(registry.entries()).hasSize(1);
    }

    @Test
    @DisplayName("recording the same name twice overwrites the earlier entry")
    void record_SameName_OverwritesPreviousEntry() {
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.FAILED, new RuntimeException("refused"));
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED, null);

        assertThat(registry.entries()).hasSize(1);
        assertThat(registry.connectedNames()).containsExactly("ascend-audio-scribe");
    }

    @Test
    @DisplayName("DISABLED entry does not appear in connectedNames")
    void record_Disabled_DoesNotAppearInConnectedNames() {
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.DISABLED, null);

        assertThat(registry.connectedNames()).isEmpty();
        assertThat(registry.entries()).hasSize(1);
    }

    @Test
    @DisplayName("resolveConnectionName prefers the client title when present")
    void resolveConnectionName_TitlePresent_ReturnsTitle() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(new McpSchema.Implementation("ascend-audio-scribe-server", "Ascend Audio Scribe Title", "0.0.1"));

        assertThat(McpClientStatusRegistry.resolveConnectionName(client)).isEqualTo("Ascend Audio Scribe Title");
    }

    @Test
    @DisplayName("resolveConnectionName falls back to the name when the title is blank")
    void resolveConnectionName_BlankTitleWithName_ReturnsName() {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(new McpSchema.Implementation("weather", "", "0.0.1"));

        assertThat(McpClientStatusRegistry.resolveConnectionName(client)).isEqualTo("weather");
    }

    @Test
    @DisplayName("resolveConnectionName gives two unnamed clients distinct, stable fallback names so they do not collapse")
    void resolveConnectionName_UnnamedClients_ReturnDistinctStableNames() {
        McpSyncClient first = mock(McpSyncClient.class);
        McpSyncClient second = mock(McpSyncClient.class);
        when(first.getClientInfo()).thenReturn(null);
        when(second.getClientInfo()).thenReturn(null);

        String firstName = McpClientStatusRegistry.resolveConnectionName(first);
        String secondName = McpClientStatusRegistry.resolveConnectionName(second);

        assertThat(firstName).startsWith("unknown-");
        assertThat(secondName).startsWith("unknown-");
        assertThat(firstName).isNotEqualTo(secondName);
        assertThat(McpClientStatusRegistry.resolveConnectionName(first)).isEqualTo(firstName);
    }
}
