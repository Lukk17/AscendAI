package com.lukk.ascend.ai.agent.service.chat;

import com.lukk.ascend.ai.agent.service.provider.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.provider.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.provider.ToolCallTracker;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import io.micrometer.core.instrument.Timer;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.tool.ToolCallbackProvider;

import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@ExtendWith(MockitoExtension.class)
class McpToolMetricsTest {

    private static final String FAST_TOOL = "fast_tool";
    private static final String SLOW_TOOL = "slow_tool";
    private static final String FAILING_TOOL = "failing_tool";

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private ToolCallbackProvider toolCallbackProvider;

    @Mock
    private ChatResponseContentResolver chatResponseContentResolver;

    @Mock
    private PromptCacheStrategyResolver cacheStrategyResolver;

    @Mock
    private ToolCallTracker toolCallTracker;

    private SimpleMeterRegistry registry;
    private ChatExecutor chatExecutor;

    @BeforeEach
    void setUp() {
        // given
        registry = new SimpleMeterRegistry();
        chatExecutor = new ChatExecutor(chatModelResolver, toolCallbackProvider, chatResponseContentResolver,
                cacheStrategyResolver, registry, toolCallTracker);
    }

    @Test
    @DisplayName("mcp.tool.duration records count 1 per tool with ok/error outcomes and slow tool time above 200 ms")
    void toolCallbacks_WhenRunThroughChatExecutor_ThenRecordsDurationPerToolWithOutcome() throws Exception {
        // given
        String fastMarker = "fast-ok";
        String slowMarker = "slow-ok";

        // when
        String fastResult = chatExecutor.invokeToolWithMetrics(FAST_TOOL, () -> fastMarker);
        String slowResult = chatExecutor.invokeToolWithMetrics(SLOW_TOOL, () -> {
            Thread.sleep(200);
            return slowMarker;
        });
        assertThatThrownBy(() -> chatExecutor.invokeToolWithMetrics(FAILING_TOOL, () -> {
            throw new IllegalStateException("boom");
        })).isInstanceOf(IllegalStateException.class);

        // then
        assertThat(fastResult).isEqualTo(fastMarker);
        assertThat(slowResult).isEqualTo(slowMarker);
        Timer fastTimer = registry.find("mcp.tool.duration").tag("tool", FAST_TOOL).tag("outcome", "ok").timer();
        assertThat(fastTimer).isNotNull();
        assertThat(fastTimer.count()).isEqualTo(1);
        Timer slowTimer = registry.find("mcp.tool.duration").tag("tool", SLOW_TOOL).tag("outcome", "ok").timer();
        assertThat(slowTimer).isNotNull();
        assertThat(slowTimer.count()).isEqualTo(1);
        assertThat(slowTimer.totalTime(TimeUnit.MILLISECONDS)).isGreaterThanOrEqualTo(200.0);
        Timer failingTimer = registry.find("mcp.tool.duration").tag("tool", FAILING_TOOL).tag("outcome", "error").timer();
        assertThat(failingTimer).isNotNull();
        assertThat(failingTimer.count()).isEqualTo(1);
    }
}
