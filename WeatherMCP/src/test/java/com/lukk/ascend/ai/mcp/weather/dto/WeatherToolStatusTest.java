package com.lukk.ascend.ai.mcp.weather.dto;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class WeatherToolStatusTest {

    @Test
    @DisplayName("wire() returns the snake_case JSON value for every enum constant")
    void wire_returnsExpectedSerialisedValueForEachConstant() {
        // then
        assertThat(WeatherToolStatus.OK.wire()).isEqualTo("ok");
        assertThat(WeatherToolStatus.CITY_NOT_FOUND.wire()).isEqualTo("city_not_found");
        assertThat(WeatherToolStatus.NO_RESULTS.wire()).isEqualTo("no_results");
        assertThat(WeatherToolStatus.UPSTREAM_UNAVAILABLE.wire()).isEqualTo("upstream_unavailable");
        assertThat(WeatherToolStatus.INVALID_INPUT.wire()).isEqualTo("invalid_input");
    }
}
