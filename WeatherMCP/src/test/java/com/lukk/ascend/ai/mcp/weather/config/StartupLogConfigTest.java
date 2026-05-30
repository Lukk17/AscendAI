package com.lukk.ascend.ai.mcp.weather.config;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.MockedStatic;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.ToolCallbackProvider;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.core.env.Environment;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.core.io.Resource;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatNoException;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.mockStatic;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.spy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class StartupLogConfigTest {

    private static final String PORT = "9998";
    private static final String APP_NAME = "test-weather-mcp";
    private static final String PROBE_URL = "https://geocoding-api.open-meteo.com/v1/search?name=Berlin&count=1";
    private static final Resource EMPTY_BANNER = new ByteArrayResource("".getBytes(StandardCharsets.UTF_8));

    @Mock
    private Environment env;

    @Mock
    private ObjectProvider<ToolCallbackProvider> toolCallbackProvider;

    @Test
    @DisplayName("constructor produces instance silently when banner resource throws IOException")
    void constructor_bannerResourceThrowsIOException_fallsBackToEmptyBanner() throws IOException {
        // given
        Resource brokenResource = mock(Resource.class);
        when(brokenResource.getInputStream()).thenThrow(new IOException("simulated read error"));

        // then
        assertThatNoException().isThrownBy(() ->
                new StartupLogConfig(env, toolCallbackProvider, brokenResource));
    }

    @Test
    @DisplayName("onReadinessChange does nothing when state is REFUSING_TRAFFIC")
    void onReadinessChange_refusingTraffic_returnsEarlyWithoutReadingEnv() {
        // given
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);
        AvailabilityChangeEvent<ReadinessState> event = mockEvent(ReadinessState.REFUSING_TRAFFIC);

        // when
        config.onReadinessChange(event);

        // then
        verify(env, never()).getProperty(anyString());
        verify(env, never()).getProperty(anyString(), anyString());
    }

    @Test
    @DisplayName("onReadinessChange uses https when server.ssl.key-store property is present")
    void onReadinessChange_sslKeyStorePresent_logsHttpsUrl() {
        // given
        stubAcceptingEnv();
        when(env.getProperty("server.ssl.key-store")).thenReturn("/etc/ssl/server.keystore");
        stubToolProvider(buildToolProvider("weather.current"));
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("onReadinessChange shows 'default' profile label when no active profiles exist")
    void onReadinessChange_noActiveProfiles_logsDefaultProfileLabel() {
        // given
        stubAcceptingEnv();
        when(env.getActiveProfiles()).thenReturn(new String[0]);
        stubToolProvider(buildToolProvider("weather.current"));
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("onReadinessChange falls back to localhost when InetAddress.getLocalHost throws UnknownHostException")
    void onReadinessChange_unknownHostException_fallsBackToLocalhost() {
        // given
        stubAcceptingEnv();
        stubToolProvider(buildToolProvider("weather.current"));
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        try (MockedStatic<InetAddress> inetMock = mockStatic(InetAddress.class)) {
            inetMock.when(InetAddress::getLocalHost).thenThrow(new UnknownHostException("no host"));
            assertThatNoException().isThrownBy(() ->
                    config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
        }
    }

    @Test
    @DisplayName("onReadinessChange logs warning when ToolCallbackProvider is not available")
    void onReadinessChange_toolProviderMissing_logsWarning() {
        // given
        stubAcceptingEnv();
        when(toolCallbackProvider.getIfAvailable()).thenReturn(null);
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("onReadinessChange logs 'no tools registered' when provider returns empty callbacks")
    void onReadinessChange_toolProviderReturnsNoTools_logsNoToolsMessage() {
        // given
        stubAcceptingEnv();
        ToolCallbackProvider emptyProvider = mock(ToolCallbackProvider.class);
        when(emptyProvider.getToolCallbacks()).thenReturn(new ToolCallback[0]);
        when(toolCallbackProvider.getIfAvailable()).thenReturn(emptyProvider);
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("onReadinessChange logs FAILED when getToolCallbacks throws an exception")
    void onReadinessChange_toolProviderThrowsException_logsFailed() {
        // given
        stubAcceptingEnv();
        ToolCallbackProvider faultyProvider = mock(ToolCallbackProvider.class);
        when(faultyProvider.getToolCallbacks()).thenThrow(new RuntimeException("tool listing exploded"));
        when(toolCallbackProvider.getIfAvailable()).thenReturn(faultyProvider);
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("onReadinessChange logs tool names when provider returns multiple populated callbacks")
    void onReadinessChange_toolProviderReturnsTwoTools_logsToolNames() {
        // given
        stubAcceptingEnv();
        stubToolProvider(buildToolProvider("weather.current", "weather.forecast"));
        StartupLogConfig config = new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER);

        // then
        assertThatNoException().isThrownBy(() -> config.onReadinessChange(mockEvent(ReadinessState.ACCEPTING_TRAFFIC)));
    }

    @Test
    @DisplayName("probeUrl returns Warning string when executeProbe yields a non-2xx status code")
    void probeUrl_nonSuccessStatus_returnsWarning() {
        // given
        StartupLogConfig spy = spy(new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER));
        doReturn(503).when(spy).executeProbe(anyString());

        // when
        String result = spy.probeUrl(PROBE_URL);

        // then
        assertThat(result).contains("[Warning (status=503)]");
    }

    @Test
    @DisplayName("probeUrl returns FAILED string when executeProbe throws an exception")
    void probeUrl_executeThrows_returnsFailed() {
        // given
        StartupLogConfig spy = spy(new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER));
        doThrow(new RuntimeException("connection refused")).when(spy).executeProbe(anyString());

        // when
        String result = spy.probeUrl(PROBE_URL);

        // then
        assertThat(result).endsWith("[FAILED]");
    }

    @Test
    @DisplayName("probeUrl returns Connected string when executeProbe yields HTTP 200")
    void probeUrl_successStatus_returnsConnected() {
        // given
        StartupLogConfig spy = spy(new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER));
        doReturn(200).when(spy).executeProbe(anyString());

        // when
        String result = spy.probeUrl(PROBE_URL);

        // then
        assertThat(result).endsWith("[Connected]");
    }

    @Test
    @DisplayName("probeUrl returns Warning string when executeProbe yields an informational status below 200")
    void probeUrl_informationalStatus_returnsWarning() {
        // given
        StartupLogConfig spy = spy(new StartupLogConfig(env, toolCallbackProvider, EMPTY_BANNER));
        doReturn(100).when(spy).executeProbe(anyString());

        // when
        String result = spy.probeUrl(PROBE_URL);

        // then
        assertThat(result).contains("[Warning (status=100)]");
    }

    private static AvailabilityChangeEvent<ReadinessState> mockEvent(ReadinessState state) {
        return new AvailabilityChangeEvent<>(new Object(), state);
    }

    private void stubAcceptingEnv() {
        doReturn(PORT).when(env).getProperty("server.port", "9998");
        doReturn(PORT).when(env).getProperty("local.server.port", PORT);
        doReturn(null).when(env).getProperty("server.ssl.key-store");
        doReturn(APP_NAME).when(env).getProperty("spring.application.name", "ascend-ai-weather-mcp");
        doReturn(new String[]{"test"}).when(env).getActiveProfiles();
    }

    private void stubToolProvider(ToolCallbackProvider provider) {
        when(toolCallbackProvider.getIfAvailable()).thenReturn(provider);
    }

    private static ToolCallbackProvider buildToolProvider(String... toolNames) {
        ToolCallback[] callbacks = new ToolCallback[toolNames.length];
        for (int i = 0; i < toolNames.length; i++) {
            ToolCallback cb = mock(ToolCallback.class);
            ToolDefinition def = mock(ToolDefinition.class);
            when(def.name()).thenReturn(toolNames[i]);
            when(cb.getToolDefinition()).thenReturn(def);
            callbacks[i] = cb;
        }
        ToolCallbackProvider provider = mock(ToolCallbackProvider.class);
        when(provider.getToolCallbacks()).thenReturn(callbacks);

        return provider;
    }
}
