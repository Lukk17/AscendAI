package com.lukk.ascend.ai.agent.service.provider;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ToolCallTrackerTest {

    private final ToolCallTracker toolCallTracker = new ToolCallTracker();

    @Test
    @DisplayName("drain returns an empty list when nothing was recorded")
    void drain_WhenNothingRecorded_ThenReturnsEmptyList() {
        // when
        List<String> drained = toolCallTracker.drain();

        // then
        assertThat(drained).isEmpty();
    }

    @Test
    @DisplayName("drain returns each recorded tool name")
    void drain_WhenToolsRecorded_ThenReturnsTheirNames() {
        // given
        toolCallTracker.record("weather_current");
        toolCallTracker.record("weather_forecast");

        // when
        List<String> drained = toolCallTracker.drain();

        // then
        assertThat(drained).containsExactly("weather_current", "weather_forecast");
    }

    @Test
    @DisplayName("drain deduplicates a tool name recorded more than once")
    void drain_WhenSameToolRecordedTwice_ThenReturnsItOnce() {
        // given
        toolCallTracker.record("weather_current");
        toolCallTracker.record("weather_current");

        // when
        List<String> drained = toolCallTracker.drain();

        // then
        assertThat(drained).containsExactly("weather_current");
    }

    @Test
    @DisplayName("drain clears recorded state so a second drain is empty")
    void drain_WhenCalledTwice_ThenSecondCallIsEmpty() {
        // given
        toolCallTracker.record("weather_current");
        toolCallTracker.drain();

        // when
        List<String> secondDrain = toolCallTracker.drain();

        // then
        assertThat(secondDrain).isEmpty();
    }

    @Test
    @DisplayName("reset clears recorded state so drain returns an empty list")
    void reset_WhenToolsWereRecorded_ThenDrainReturnsEmptyList() {
        // given
        toolCallTracker.record("weather_current");

        // when
        toolCallTracker.reset();

        // then
        assertThat(toolCallTracker.drain()).isEmpty();
    }
}
