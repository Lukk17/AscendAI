package com.lukk.ascend.ai.mcp.weather.dto;

public record ResolvedLocation(
        String name,
        String country,
        String countryCode,
        Double latitude,
        Double longitude
) {
    public static ResolvedLocation from(GeoResult result) {
        return new ResolvedLocation(
                result.name(),
                result.country(),
                result.countryCode(),
                result.latitude(),
                result.longitude()
        );
    }
}
