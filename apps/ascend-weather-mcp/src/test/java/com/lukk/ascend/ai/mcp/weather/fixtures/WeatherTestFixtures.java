package com.lukk.ascend.ai.mcp.weather.fixtures;

import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;

public final class WeatherTestFixtures {

    private WeatherTestFixtures() {
    }

    public static final String CITY_WARSAW = "Warsaw";
    public static final String COUNTRY_PL = "PL";
    public static final String UNIT_CELSIUS = "celsius";
    public static final String UNIT_FAHRENHEIT = "fahrenheit";
    public static final String LANG_EN = "en";

    public static final GeoResult WARSAW = new GeoResult(52.23, 21.01, "Warsaw", "Poland", "PL");
}
