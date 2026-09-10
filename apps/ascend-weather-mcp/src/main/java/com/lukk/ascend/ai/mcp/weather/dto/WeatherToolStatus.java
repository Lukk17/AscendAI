package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonValue;

public enum WeatherToolStatus {

    OK("ok"),
    CITY_NOT_FOUND("city_not_found"),
    NO_RESULTS("no_results"),
    UPSTREAM_UNAVAILABLE("upstream_unavailable"),
    INVALID_INPUT("invalid_input");

    private final String wire;

    WeatherToolStatus(String wire) {
        this.wire = wire;
    }

    @JsonValue
    public String wire() {
        return wire;
    }
}
