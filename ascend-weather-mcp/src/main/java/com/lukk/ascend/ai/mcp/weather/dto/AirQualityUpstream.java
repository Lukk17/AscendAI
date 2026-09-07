package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record AirQualityUpstream(
        Double latitude,
        Double longitude,
        Current current
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Current(
            Double pm10,
            @JsonProperty("pm2_5") Double pm25,
            @JsonProperty("us_aqi") Integer usAqi,
            @JsonProperty("european_aqi") Integer europeanAqi
    ) {
    }
}
