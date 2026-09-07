package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record GeoResult(
        Double latitude,
        Double longitude,
        String name,
        String country,
        @JsonProperty("country_code") String countryCode
) {
}
