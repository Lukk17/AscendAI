package com.lukk.ascend.ai.mcp.weather.dto;

import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;

import java.time.Instant;

public record HistoricalWeatherResult(
        WeatherToolStatus status,
        String message,
        String requestedQuery,
        ResolvedLocation location,
        DailyForecast day,
        String temperatureUnit,
        Instant fetchedAt,
        String source
) {

    public static HistoricalWeatherResult ok(ResolvedLocation location, DailyForecast day, String temperatureUnit) {
        return new HistoricalWeatherResult(WeatherToolStatus.OK, null, null,
                location, day, temperatureUnit, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static HistoricalWeatherResult cityNotFound(String requestedQuery) {
        return new HistoricalWeatherResult(WeatherToolStatus.CITY_NOT_FOUND, "Location not found",
                requestedQuery, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static HistoricalWeatherResult upstreamUnavailable() {
        return new HistoricalWeatherResult(WeatherToolStatus.UPSTREAM_UNAVAILABLE, "Weather service unavailable",
                null, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static HistoricalWeatherResult invalidInput(String message, String requestedQuery) {
        return new HistoricalWeatherResult(WeatherToolStatus.INVALID_INPUT, message,
                requestedQuery, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }
}
