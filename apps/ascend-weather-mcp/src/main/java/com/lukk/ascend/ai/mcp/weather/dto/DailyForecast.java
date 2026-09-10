package com.lukk.ascend.ai.mcp.weather.dto;

public record DailyForecast(
        String date,
        Double maxTemp,
        Double minTemp,
        Double precipitationSum,
        Integer weatherCode
) {
}
