package com.lukk.ascend.ai.mcp.weather.config;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class WeatherApiEndpoints {

    public static final String GEOCODING = "https://geocoding-api.open-meteo.com/v1/search";
    public static final String FORECAST = "https://api.open-meteo.com/v1/forecast";
    public static final String ARCHIVE = "https://archive-api.open-meteo.com/v1/archive";
    public static final String AIR_QUALITY = "https://air-quality-api.open-meteo.com/v1/air-quality";

    public static final String GEOCODING_PROBE = GEOCODING + "?name=Berlin&count=1";
    public static final String FORECAST_PROBE = FORECAST + "?latitude=52&longitude=13&current_weather=true";

    public static final String SOURCE = "open-meteo";
}
