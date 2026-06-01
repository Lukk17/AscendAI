package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;

import java.time.Instant;
import java.util.List;

public record GeocodeResult(
        WeatherToolStatus status,
        String message,
        String requestedQuery,
        List<ResolvedLocation> candidates,
        @JsonFormat(shape = JsonFormat.Shape.STRING) Instant fetchedAt,
        String source
) {

    public static GeocodeResult ok(List<ResolvedLocation> candidates) {
        return new GeocodeResult(WeatherToolStatus.OK, null, null,
                candidates, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static GeocodeResult noResults(String requestedQuery) {
        return new GeocodeResult(WeatherToolStatus.NO_RESULTS, "No results found",
                requestedQuery, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static GeocodeResult upstreamUnavailable() {
        return new GeocodeResult(WeatherToolStatus.UPSTREAM_UNAVAILABLE, "Geocoding service unavailable",
                null, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }

    public static GeocodeResult invalidInput(String message, String requestedQuery) {
        return new GeocodeResult(WeatherToolStatus.INVALID_INPUT, message,
                requestedQuery, null, Instant.now(), WeatherApiEndpoints.SOURCE);
    }
}
