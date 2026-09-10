package com.lukk.ascend.ai.agent.integration;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.lukk.ascend.ai.agent.config.StartupLogConfig;
import com.lukk.ascend.ai.agent.config.mcp.McpClientEntry;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatus;
import com.lukk.ascend.ai.agent.config.mcp.McpClientStatusRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.availability.AvailabilityChangeEvent;
import org.springframework.boot.availability.LivenessState;
import org.springframework.boot.availability.ReadinessState;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

/**
 * Verifies the startup banner emitted by {@link StartupLogConfig} on the
 * {@code ApplicationReadyEvent}-equivalent {@code AvailabilityChangeEvent<ReadinessState>}.
 *
 * <p>Strategy: attach a Logback {@link ListAppender} to the {@code StartupLogConfig}
 * logger before re-publishing the readiness event. The original event already fired
 * during context start (before the appender attached), so we re-fire it inside the
 * test and capture the second emission. The handler is idempotent — it just logs.
 */
class StartupBannerIT extends TestcontainersBase {

    @MockitoBean
    McpClientStatusRegistry mcpClientStatusRegistry;

    @Autowired
    ApplicationContext applicationContext;

    private Logger startupLogger;
    private ListAppender<ILoggingEvent> appender;

    @BeforeEach
    void attachAppender() {
        startupLogger = (Logger) LoggerFactory.getLogger(StartupLogConfig.class);
        appender = new ListAppender<>();
        appender.start();
        startupLogger.addAppender(appender);

        when(mcpClientStatusRegistry.entries()).thenReturn(List.of(
                new McpClientEntry("ascend-audio-scribe", "http://localhost:7017", McpClientStatus.CONNECTED),
                new McpClientEntry("ascend-weather-mcp", "http://localhost:9998", McpClientStatus.FAILED)
        ));
    }

    @AfterEach
    void detachAppender() {
        startupLogger.detachAppender(appender);
    }

    @Test
    void banner_reportsStructureWithStatusMarkersAndPromptEndpoint() {
        // Re-publish readiness so the @EventListener writes to our freshly attached appender.
        AvailabilityChangeEvent.publish(applicationContext, ReadinessState.ACCEPTING_TRAFFIC);

        String banner = appender.list.stream()
                .map(ILoggingEvent::getFormattedMessage)
                .reduce("", (a, b) -> a + "\n" + b);

        // Banner must be emitted with the four backing-service labels and the MCP tools line.
        // We assert structure, not connectivity — BackingServicesIT covers actual reachability,
        // and this IT must not flake when a singleton container's port races the JVM's resolver.
        assertThat(banner).contains("Application '");
        assertThat(banner).contains("Postgres:");
        assertThat(banner).contains("Redis:");
        assertThat(banner).contains("Qdrant:");
        assertThat(banner).contains("S3 (Floci):");
        assertThat(banner).contains("AscendMemory:");
        assertThat(banner).contains("Chat history:");
        assertThat(banner).contains("MCP servers:");
        assertThat(banner).contains("[Connected]");
        assertThat(banner).contains("[FAILED]");
        assertThat(banner).contains("Aggregate:");

        // Each backing-service line carries one of the status markers — this guards against
        // an accidental refactor that drops the [Connected]/[FAILED]/[Warning]/[Disabled] tag.
        assertThat(banner).containsPattern("(\\[Connected]|\\[FAILED]|\\[Warning]|\\[Disabled])");

        // Prompt endpoint line + the actual mapped path on PromptController.
        assertThat(banner).contains("MAIN PROMPT ENDPOINT");
        assertThat(banner).contains("/api/v1/ai/prompt");
    }

    @Test
    void banner_isSkippedForNonAcceptingTrafficStates() {
        // Sanity check: the listener early-returns for non-ACCEPTING_TRAFFIC events,
        // so re-publishing a different readiness/liveness state must not emit the banner.
        AvailabilityChangeEvent.publish(applicationContext, ReadinessState.REFUSING_TRAFFIC);
        AvailabilityChangeEvent.publish(applicationContext, LivenessState.CORRECT);

        boolean hasBanner = appender.list.stream()
                .map(ILoggingEvent::getFormattedMessage)
                .anyMatch(msg -> msg.contains("MAIN PROMPT ENDPOINT"));

        assertThat(hasBanner).isFalse();
    }
}
