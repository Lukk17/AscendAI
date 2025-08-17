package com.lukk.ai.mcp.service;

import com.lukk.ai.mcp.dto.WeatherResponse;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;

@Service
public class WeatherToolService {

    @Tool(description = "Get the current weather for a specific city. The user must provide the location.")
    public WeatherResponse getCurrentWeather(@ToolParam(description = "The name of a city or a country") String location) {
        if (location != null && location.toLowerCase().contains("warsaw")) {
            return new WeatherResponse(117, "solar apocalypse");
        }
        return new WeatherResponse(0, "whatever");
    }
}
