package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;

import java.time.Instant;

public record CurrentWeatherResult(
        WeatherToolStatus status,
        String message,
        String requestedQuery,
        ResolvedLocation location,
        Temperature temperature,
        Integer weatherCode,
        Wind wind,
        String observedAt,
        @JsonFormat(shape = JsonFormat.Shape.STRING) Instant fetchedAt,
        String source
) {

    public static CurrentWeatherResult ok(ResolvedLocation location,
                                          Temperature temperature,
                                          Integer weatherCode,
                                          Wind wind,
                                          String observedAt) {
        return new CurrentWeatherResult(WeatherToolStatus.OK, null, null,
                location, temperature, weatherCode, wind, observedAt,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static CurrentWeatherResult cityNotFound(String requestedQuery) {
        return new CurrentWeatherResult(WeatherToolStatus.CITY_NOT_FOUND, "Location not found",
                requestedQuery, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static CurrentWeatherResult upstreamUnavailable() {
        return new CurrentWeatherResult(WeatherToolStatus.UPSTREAM_UNAVAILABLE, "Weather service unavailable",
                null, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static CurrentWeatherResult invalidInput(String message, String requestedQuery) {
        return new CurrentWeatherResult(WeatherToolStatus.INVALID_INPUT, message,
                requestedQuery, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }
}
