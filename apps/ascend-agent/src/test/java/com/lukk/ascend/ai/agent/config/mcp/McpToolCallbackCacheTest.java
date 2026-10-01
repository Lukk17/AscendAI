package com.lukk.ascend.ai.agent.config.mcp;

import com.lukk.ascend.ai.agent.config.properties.McpStartupProperties;
import com.lukk.ascend.ai.agent.config.properties.McpToolCacheProperties;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.spec.McpSchema;
import io.modelcontextprotocol.spec.McpTransportSessionNotFoundException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.mcp.McpToolsChangedEvent;
import org.springframework.ai.tool.ToolCallback;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class McpToolCallbackCacheTest {

    private static final String SCRIBE = "ascend-audio-scribe";
    private static final String WEATHER = "ascend-weather-mcp";
    private static final String SCRIBE_URL = "http://localhost:7017";
    private static final String WEATHER_URL = "http://localhost:9998";
    private static final Duration TTL = Duration.ofSeconds(60);

    private McpSyncClient scribeClient;
    private McpSyncClient weatherClient;
    private McpClientStatusRegistry registry;
    private MutableClock clock;
    private McpToolCallbackCache toolCallbackCache;
    private FilteredToolCallbackProvider provider;

    @BeforeEach
    void setUp() {
        scribeClient = mockClient(SCRIBE, "transcribe");
        weatherClient = mockClient(WEATHER, "weather_current");
        registry = new McpClientStatusRegistry();
        clock = new MutableClock(Instant.parse("2026-09-24T10:00:00Z"));

        McpToolCacheProperties cacheProperties = new McpToolCacheProperties();
        cacheProperties.setTtl(TTL);
        toolCallbackCache = new McpToolCallbackCache(registry, cacheProperties, clock);
        provider = new FilteredToolCallbackProvider(
                List.of(scribeClient, weatherClient), registry, new McpStartupProperties(), toolCallbackCache);
    }

    @Test
    @DisplayName("two consecutive prompts with an unchanged connected set list each server's tools once")
    void getToolCallbacks_ConnectedSetUnchanged_ListsToolsOnce() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        registry.record(WEATHER, WEATHER_URL, McpClientStatus.CONNECTED);

        // when
        ToolCallback[] first = provider.getToolCallbacks();
        ToolCallback[] second = provider.getToolCallbacks();

        // then
        assertThat(toolNames(first)).containsExactlyInAnyOrder("transcribe", "weather_current");
        assertThat(toolNames(second)).containsExactlyInAnyOrder("transcribe", "weather_current");
        verify(scribeClient, times(1)).listTools();
        verify(weatherClient, times(1)).listTools();
    }

    @Test
    @DisplayName("a server joining the connected set forces a fresh listing that includes its tools")
    void getToolCallbacks_ConnectedSetChanges_ListsToolsAgain() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        registry.record(WEATHER, WEATHER_URL, McpClientStatus.FAILED);
        assertThat(toolNames(provider.getToolCallbacks())).containsExactly("transcribe");

        // when
        registry.record(WEATHER, WEATHER_URL, McpClientStatus.CONNECTED);
        ToolCallback[] afterReconnect = provider.getToolCallbacks();

        // then
        assertThat(toolNames(afterReconnect)).containsExactlyInAnyOrder("transcribe", "weather_current");
        verify(scribeClient, times(2)).listTools();
        verify(weatherClient, times(1)).listTools();
    }

    @Test
    @DisplayName("a server the registry marks failed loses its tools on the very next prompt")
    void getToolCallbacks_ServerMarkedFailed_ItsToolsDisappearOnNextPrompt() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        registry.record(WEATHER, WEATHER_URL, McpClientStatus.CONNECTED);
        assertThat(toolNames(provider.getToolCallbacks())).containsExactlyInAnyOrder("transcribe", "weather_current");

        // when
        registry.markFailed(WEATHER);
        ToolCallback[] afterFailure = provider.getToolCallbacks();

        // then
        assertThat(toolNames(afterFailure)).containsExactly("transcribe");
    }

    @Test
    @DisplayName("a listing that demotes a server is not cached under the connected set it started from")
    void getToolCallbacks_ListingDemotesServer_NextPromptListsAgainThenCaches() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        registry.record(WEATHER, WEATHER_URL, McpClientStatus.CONNECTED);
        when(weatherClient.listTools()).thenThrow(new McpTransportSessionNotFoundException("stale-session-id"));
        doThrow(new IllegalStateException("Connection refused")).when(weatherClient).initialize();

        // then
        assertThat(toolNames(provider.getToolCallbacks())).containsExactly("transcribe");
        assertThat(toolNames(provider.getToolCallbacks())).containsExactly("transcribe");
        assertThat(toolNames(provider.getToolCallbacks())).containsExactly("transcribe");

        assertThat(registry.connectedNames()).containsExactly(SCRIBE);
        verify(scribeClient, times(2)).listTools();
        verify(weatherClient, times(1)).listTools();
    }

    @Test
    @DisplayName("the cached listing is served until the expiry and relisted once it has passed")
    void getToolCallbacks_ExpiryPassed_ListsToolsAgain() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        provider.getToolCallbacks();

        clock.advance(TTL.minusMillis(1));
        provider.getToolCallbacks();
        verify(scribeClient, times(1)).listTools();

        // when
        clock.advance(Duration.ofMillis(1));
        ToolCallback[] afterExpiry = provider.getToolCallbacks();

        // then
        assertThat(toolNames(afterExpiry)).containsExactly("transcribe");
        verify(scribeClient, times(2)).listTools();
    }

    @Test
    @DisplayName("a zero expiry disables caching so every prompt lists tools")
    void getToolCallbacks_ZeroTtl_ListsToolsEveryPrompt() {
        // given
        McpToolCacheProperties disabled = new McpToolCacheProperties();
        disabled.setTtl(Duration.ZERO);
        FilteredToolCallbackProvider uncached = new FilteredToolCallbackProvider(List.of(scribeClient), registry,
                new McpStartupProperties(), new McpToolCallbackCache(registry, disabled, clock));
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);

        // when
        uncached.getToolCallbacks();
        uncached.getToolCallbacks();

        // then
        verify(scribeClient, times(2)).listTools();
    }

    @Test
    @DisplayName("an MCP tools-changed notification invalidates the cache before the expiry")
    void onToolsChanged_NotificationReceived_NextPromptListsToolsAgain() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        provider.getToolCallbacks();

        // when
        toolCallbackCache.onToolsChanged(new McpToolsChangedEvent(SCRIBE, List.of()));
        provider.getToolCallbacks();

        // then
        verify(scribeClient, times(2)).listTools();
    }

    @Test
    @DisplayName("a tools-changed notification arriving mid-listing keeps that listing out of the cache")
    void onToolsChanged_ArrivesDuringListing_ListingIsNotCached() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        McpSchema.ListToolsResult staleListing = listing("transcribe");
        doAnswer(invocation -> {
            toolCallbackCache.onToolsChanged(new McpToolsChangedEvent(SCRIBE, List.of()));

            return staleListing;
        }).doReturn(listing("transcribe")).when(scribeClient).listTools();

        // when
        provider.getToolCallbacks();
        provider.getToolCallbacks();
        provider.getToolCallbacks();

        // then
        verify(scribeClient, times(2)).listTools();
    }

    @Test
    @DisplayName("a caller mutating the returned array does not change what the next prompt receives")
    void getToolCallbacks_CallerMutatesResult_CacheUnaffected() {
        // given
        registry.record(SCRIBE, SCRIBE_URL, McpClientStatus.CONNECTED);
        ToolCallback[] first = provider.getToolCallbacks();
        first[0] = null;

        // when
        ToolCallback[] second = provider.getToolCallbacks();

        // then
        assertThat(toolNames(second)).containsExactly("transcribe");
    }

    private static McpSyncClient mockClient(String connectionName, String toolName) {
        McpSyncClient client = mock(McpSyncClient.class);
        when(client.getClientInfo()).thenReturn(
                new McpSchema.Implementation("AscendAI-Agent - " + connectionName, connectionName, "0.0.1"));
        when(client.listTools()).thenReturn(listing(toolName));

        return client;
    }

    private static McpSchema.ListToolsResult listing(String toolName) {
        McpSchema.JsonSchema inputSchema = new McpSchema.JsonSchema("object", Map.of(), List.of(), false, null, null);
        McpSchema.Tool tool = McpSchema.Tool.builder()
                .name(toolName)
                .description("stub MCP tool " + toolName)
                .inputSchema(inputSchema)
                .build();

        return new McpSchema.ListToolsResult(List.of(tool), null);
    }

    private static List<String> toolNames(ToolCallback[] callbacks) {
        return Arrays.stream(callbacks)
                .map(callback -> callback.getToolDefinition().name())
                .toList();
    }

    private static final class MutableClock extends Clock {

        private Instant now;

        private MutableClock(Instant start) {
            this.now = start;
        }

        private void advance(Duration duration) {
            now = now.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return now;
        }
    }
}
