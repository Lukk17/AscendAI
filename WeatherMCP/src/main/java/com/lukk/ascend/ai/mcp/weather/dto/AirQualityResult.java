package com.lukk.ascend.ai.mcp.weather.dto;

import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;

import java.time.Instant;

public record AirQualityResult(
        WeatherToolStatus status,
        String message,
        String requestedQuery,
        ResolvedLocation location,
        Double pm10,
        Double pm25,
        Integer usAqi,
        Integer europeanAqi,
        Instant fetchedAt,
        String source
) {

    public static AirQualityResult ok(ResolvedLocation location,
                                      Double pm10,
                                      Double pm25,
                                      Integer usAqi,
                                      Integer europeanAqi) {
        return new AirQualityResult(WeatherToolStatus.OK, null, null,
                location, pm10, pm25, usAqi, europeanAqi,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static AirQualityResult cityNotFound(String requestedQuery) {
        return new AirQualityResult(WeatherToolStatus.CITY_NOT_FOUND, "Location not found",
                requestedQuery, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static AirQualityResult upstreamUnavailable() {
        return new AirQualityResult(WeatherToolStatus.UPSTREAM_UNAVAILABLE, "Air quality service unavailable",
                null, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static AirQualityResult invalidInput(String message, String requestedQuery) {
        return new AirQualityResult(WeatherToolStatus.INVALID_INPUT, message,
                requestedQuery, null, null, null, null, null,
                Instant.now(), WeatherApiEndpoints.SOURCE);
    }
}
