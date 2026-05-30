package com.lukk.ascend.ai.mcp.weather.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonIgnoreProperties(ignoreUnknown = true)
public record CurrentWeatherUpstream(
        Double latitude,
        Double longitude,
        @JsonProperty("current_weather") Current currentWeather
) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Current(
            Double temperature,
            @JsonProperty("windspeed") Double windSpeed,
            @JsonProperty("winddirection") Double windDirection,
            @JsonProperty("weathercode") Integer weatherCode,
            String time
    ) {
    }
}
