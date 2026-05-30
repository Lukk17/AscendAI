package com.lukk.ascend.ai.mcp.weather.dto;

import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;

import java.time.Instant;
import java.util.List;

public record ForecastResult(
        WeatherToolStatus status,
        String message,
        String requestedQuery,
        ResolvedLocation location,
        List<DailyForecast> forecast,
        String temperatureUnit,
        Instant fetchedAt,
        String source
) {

    public static ForecastResult ok(ResolvedLocation location, List<DailyForecast> forecast, String temperatureUnit) {
        return new ForecastResult(WeatherToolStatus.OK, null, null,
                location, forecast, temperatureUnit, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static ForecastResult cityNotFound(String requestedQuery) {
        return new ForecastResult(WeatherToolStatus.CITY_NOT_FOUND, "Location not found",
                requestedQuery, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static ForecastResult upstreamUnavailable() {
        return new ForecastResult(WeatherToolStatus.UPSTREAM_UNAVAILABLE, "Weather service unavailable",
                null, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static ForecastResult invalidInput(String message, String requestedQuery) {
        return new ForecastResult(WeatherToolStatus.INVALID_INPUT, message,
                requestedQuery, null, null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }
}
