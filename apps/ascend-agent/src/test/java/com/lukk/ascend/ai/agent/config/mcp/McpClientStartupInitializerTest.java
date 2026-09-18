package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpStartupProperties;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import org.assertj.core.groups.Tuple;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.mcp.client.common.autoconfigure.properties.McpStreamableHttpClientProperties;

import java.time.Duration;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class McpClientStartupInitializerTest {

    private static final String AUDIO_SCRIBE = "ascend-audio-scribe";
    private static final String AUDIO_SCRIBE_URL = "http://localhost:7017";
    private static final String WEATHER = "ascend-weather-mcp";
    private static final String WEATHER_URL = "http://localhost:9998";
    private static final String UNKNOWN_URL = "unknown";

    private McpClientStatusRegistry registry;
    private McpStartupProperties startupProperties;
    private McpStreamableHttpClientProperties streamableHttpProperties;

    @BeforeEach
    void setUp() {
        registry = new McpClientStatusRegistry();
        startupProperties = new McpStartupProperties();
        streamableHttpProperties = new McpStreamableHttpClientProperties();
        streamableHttpProperties.getConnections().put(AUDIO_SCRIBE,
                new McpStreamableHttpClientProperties.ConnectionParameters(AUDIO_SCRIBE_URL, null));
        streamableHttpProperties.getConnections().put(WEATHER,
                new McpStreamableHttpClientProperties.ConnectionParameters(WEATHER_URL, null));
    }

    @Test
    @DisplayName("initialize records every client that handshakes successfully as CONNECTED with its configured URL")
    void initialize_AllClientsHandshake_RecordsConnectedWithConfiguredUrls() {
        McpSyncClient audioScribe = clientNamed(AUDIO_SCRIBE);
        McpSyncClient weather = clientNamed(WEATHER);

        initializerFor(audioScribe, weather).initialize();

        verify(audioScribe).initialize();
        verify(weather).initialize();
        assertThat(registry.connectedNames()).containsExactlyInAnyOrder(AUDIO_SCRIBE, WEATHER);
        assertThat(registry.entries())
                .extracting(McpClientEntry::name, McpClientEntry::url, McpClientEntry::status)
                .containsExactlyInAnyOrder(
                        Tuple.tuple(AUDIO_SCRIBE, AUDIO_SCRIBE_URL, McpClientStatus.CONNECTED),
                        Tuple.tuple(WEATHER, WEATHER_URL, McpClientStatus.CONNECTED));
    }

    @Test
    @DisplayName("initialize isolates a failing client so the remaining clients still connect")
    void initialize_OneClientRefusesConnection_OtherClientsStillConnect() {
        McpSyncClient audioScribe = clientNamed(AUDIO_SCRIBE);
        McpSyncClient weather = clientNamed(WEATHER);
        doThrow(new IllegalStateException("Connection refused")).when(weather).initialize();

        initializerFor(audioScribe, weather).initialize();

        assertThat(registry.connectedNames()).containsExactly(AUDIO_SCRIBE);
        assertThat(entryFor(WEATHER).status()).isEqualTo(McpClientStatus.FAILED);
        assertThat(entryFor(WEATHER).url()).isEqualTo(WEATHER_URL);
    }

    @Test
    @DisplayName("initialize records FAILED and returns within the configured timeout when a handshake stalls")
    void initialize_HandshakeStalls_RecordsFailedWithinTimeout() {
        startupProperties.setInitTimeout(Duration.ofMillis(100));
        McpSyncClient stalling = clientNamed(WEATHER);
        doAnswer(invocation -> {
            TimeUnit.SECONDS.sleep(5);
            return null;
        }).when(stalling).initialize();

        long startedAt = System.nanoTime();
        initializerFor(stalling).initialize();
        Duration elapsed = Duration.ofNanos(System.nanoTime() - startedAt);

        assertThat(entryFor(WEATHER).status()).isEqualTo(McpClientStatus.FAILED);
        assertThat(registry.connectedNames()).isEmpty();
        assertThat(elapsed).isLessThan(Duration.ofSeconds(1));
    }

    @Test
    @DisplayName("initialize records an unconfigured connection name with an unknown URL rather than failing")
    void initialize_ClientNameNotInConnectionMap_RecordsUnknownUrl() {
        McpSyncClient orphan = clientNamed("not-configured");

        initializerFor(orphan).initialize();

        assertThat(entryFor("not-configured").url()).isEqualTo(UNKNOWN_URL);
        assertThat(entryFor("not-configured").status()).isEqualTo(McpClientStatus.CONNECTED);
    }

    @Test
    @DisplayName("initialize records an unknown URL when the configured connection carries no url")
    void initialize_ConnectionWithoutUrl_RecordsUnknownUrl() {
        streamableHttpProperties.getConnections().put(WEATHER,
                new McpStreamableHttpClientProperties.ConnectionParameters(null, "/mcp"));
        McpSyncClient weather = clientNamed(WEATHER);

        initializerFor(weather).initialize();

        assertThat(entryFor(WEATHER).url()).isEqualTo(UNKNOWN_URL);
    }

    @Test
    @DisplayName("initialize records an unknown URL when no streamable-http connections are configured at all")
    void initialize_EmptyConnectionMap_RecordsUnknownUrl() {
        streamableHttpProperties.getConnections().clear();
        McpSyncClient weather = clientNamed(WEATHER);

        initializerFor(weather).initialize();

        assertThat(entryFor(WEATHER).url()).isEqualTo(UNKNOWN_URL);
    }

    @Test
    @DisplayName("initialize records an unknown URL when the connection map itself is absent")
    void initialize_NullConnectionMap_RecordsUnknownUrl() {
        McpStreamableHttpClientProperties propertiesWithoutMap = mock(McpStreamableHttpClientProperties.class);
        when(propertiesWithoutMap.getConnections()).thenReturn(null);
        McpSyncClient weather = clientNamed(WEATHER);

        new McpClientStartupInitializer(List.of(weather), registry, startupProperties, propertiesWithoutMap)
                .initialize();

        assertThat(entryFor(WEATHER).url()).isEqualTo(UNKNOWN_URL);
    }

    @Test
    @DisplayName("initialize records a client whose name cannot be resolved without letting the exception escape")
    void initialize_NameResolutionThrows_RecordsFallbackEntryAndDoesNotPropagate() {
        McpSyncClient broken = mock(McpSyncClient.class);
        when(broken.getClientInfo()).thenThrow(new IllegalStateException("transport gone"));

        initializerFor(broken).initialize();

        verify(broken, never()).initialize();
        Collection<McpClientEntry> entries = registry.entries();
        assertThat(entries).hasSize(1);
        McpClientEntry entry = entries.iterator().next();
        assertThat(entry.name()).startsWith("unknown-");
        assertThat(entry.url()).isEqualTo(UNKNOWN_URL);
        assertThat(entry.status()).isEqualTo(McpClientStatus.FAILED);
    }

    @Test
    @DisplayName("initialize with no configured clients records nothing and does not throw")
    void initialize_NoClients_RecordsNothing() {
        initializerFor().initialize();

        assertThat(registry.entries()).isEmpty();
    }

    private McpClientStartupInitializer initializerFor(McpSyncClient... clients) {
        return new McpClientStartupInitializer(List.of(clients), registry, startupProperties, streamableHttpProperties);
    }

    private McpClientEntry entryFor(String name) {
        return registry.entries().stream()
                .filter(entry -> entry.name().equals(name))
                .findFirst()
                .orElseThrow(() -> new AssertionError("No registry entry recorded for '" + name + "'"));
    }

    private static McpSyncClient clientNamed(String connectionName) {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(
                new McpSchema.Implementation("AscendAI-Agent - " + connectionName, connectionName, "0.0.1"));

        return client;
    }
}
