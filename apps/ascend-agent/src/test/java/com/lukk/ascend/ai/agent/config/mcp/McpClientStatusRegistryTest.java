package com.lukk.ascend.ai.agent.config.mcp;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Collection;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class McpClientStatusRegistryTest {

    private McpClientStatusRegistry registry;

    @BeforeEach
    void setUp() {
        registry = new McpClientStatusRegistry();
    }

    @Test
    @DisplayName("entries returns empty collection when nothing is recorded")
    void entries_WhenEmpty_ReturnsEmptyCollection() {
        // then
        assertThat(registry.entries()).isEmpty();
    }

    @Test
    @DisplayName("connectedNames returns empty set when nothing is recorded")
    void connectedNames_WhenEmpty_ReturnsEmptySet() {
        // then
        assertThat(registry.connectedNames()).isEmpty();
    }

    @Test
    @DisplayName("record persists a CONNECTED entry that appears in entries and connectedNames")
    void record_Connected_AppearsInEntriesAndConnectedNames() {
        // when
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);

        // then
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
        // when
        registry.record("ascend-weather-mcp", "http://localhost:9998", McpClientStatus.FAILED);

        // then
        assertThat(registry.entries()).hasSize(1);
        assertThat(registry.connectedNames()).isEmpty();
    }

    @Test
    @DisplayName("connectedNames returns only CONNECTED entries when registry has mixed states")
    void connectedNames_MixedStates_ReturnsOnlyConnected() {
        // given
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);
        registry.record("ascend-weather-mcp", "http://localhost:9998", McpClientStatus.FAILED);
        registry.record("ascend-web-hunter", "http://localhost:7021", McpClientStatus.CONNECTED);

        // when
        Set<String> connected = registry.connectedNames();

        // then
        assertThat(connected).containsExactlyInAnyOrder("ascend-audio-scribe", "ascend-web-hunter");
        assertThat(connected).doesNotContain("ascend-weather-mcp");
    }

    @Test
    @DisplayName("recording the same name twice overwrites the earlier entry")
    void record_SameName_OverwritesPreviousEntry() {
        // given
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.FAILED);
        // when
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);

        // then
        assertThat(registry.entries()).hasSize(1);
        assertThat(registry.connectedNames()).containsExactly("ascend-audio-scribe");
    }

    @Test
    @DisplayName("markFailed demotes a CONNECTED client and keeps the URL it was recorded with")
    void markFailed_ConnectedEntry_DemotedAndUrlPreserved() {
        // given
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);

        // when
        registry.markFailed("ascend-audio-scribe");

        // then
        assertThat(registry.connectedNames()).isEmpty();
        McpClientEntry entry = registry.entries().iterator().next();
        assertThat(entry.status()).isEqualTo(McpClientStatus.FAILED);
        assertThat(entry.url()).isEqualTo("http://localhost:7017");
    }

    @Test
    @DisplayName("markFailed on an unknown name records a FAILED entry with an unknown URL")
    void markFailed_UnknownName_RecordsFailedEntryWithUnknownUrl() {
        // given
        registry.markFailed("never-recorded");

        // when
        McpClientEntry entry = registry.entries().iterator().next();
        // then
        assertThat(entry.name()).isEqualTo("never-recorded");
        assertThat(entry.url()).isEqualTo("unknown");
        assertThat(entry.status()).isEqualTo(McpClientStatus.FAILED);
    }

    @Test
    @DisplayName("entries returns an immutable copy so a caller cannot mutate the registry through it")
    void entries_MutationAttempt_LeavesRegistryUntouched() {
        // given
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);

        // when
        Collection<McpClientEntry> snapshot = registry.entries();

        // then
        assertThatThrownBy(snapshot::clear).isInstanceOf(UnsupportedOperationException.class);
        assertThat(registry.entries()).hasSize(1);
        assertThat(registry.connectedNames()).containsExactly("ascend-audio-scribe");
    }

    @Test
    @DisplayName("entries snapshot does not reflect later writes to the registry")
    void entries_TakenBeforeAWrite_DoesNotSeeTheLaterWrite() {
        // given
        registry.record("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED);
        Collection<McpClientEntry> snapshot = registry.entries();

        // when
        registry.record("ascend-weather-mcp", "http://localhost:9998", McpClientStatus.FAILED);

        // then
        assertThat(snapshot).hasSize(1);
        assertThat(registry.entries()).hasSize(2);
    }
}
