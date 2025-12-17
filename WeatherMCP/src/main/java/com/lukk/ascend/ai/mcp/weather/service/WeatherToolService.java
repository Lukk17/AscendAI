package com.lukk.ascend.ai.mcp.weather.service;

import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.Map;

@Service
public class WeatherToolService {

    private final RestClient restClient;

    public WeatherToolService(RestClient.Builder restClientBuilder) {
        this.restClient = restClientBuilder.build();
    }

    @Tool(description = "Get the current weather for a specific city. The user must provide the location.")
    public String getCurrentWeather(@ToolParam(description = "The name of a city or a country") String city,
            @ToolParam(description = "Temperature unit: 'celsius' or 'fahrenheit'", required = false) String unit,
            @ToolParam(description = "Language code (e.g. 'en', 'pl', 'de')", required = false) String language) {
        // 1. Get coordinates
        String lang = (language != null && !language.isEmpty()) ? language : "en";
        String geoUrl = UriComponentsBuilder.fromHttpUrl("https://geocoding-api.open-meteo.com/v1/search")
                .queryParam("name", city)
                .queryParam("count", 1) // Limit results to 1
                .queryParam("language", lang)
                .queryParam("format", "json")
                .build()
                .toUriString();

        Map<String, Object> geoResponse = restClient.get()
                .uri(geoUrl)
                .retrieve()
                .body(Map.class);

        if (geoResponse == null || !geoResponse.containsKey("results")) {
            return "City not found: " + city;
        }

        List<Map<String, Object>> results = (List<Map<String, Object>>) geoResponse.get("results");
        if (results.isEmpty()) {
            return "City not found: " + city;
        }

        Map<String, Object> loc = results.get(0);
        double lat = (Double) loc.get("latitude");
        double lon = (Double) loc.get("longitude");

        // 2. Get weather
        String tempUnit = (unit != null && unit.equalsIgnoreCase("fahrenheit")) ? "fahrenheit" : "celsius";
        String weatherUrl = UriComponentsBuilder.fromHttpUrl("https://api.open-meteo.com/v1/forecast")
                .queryParam("latitude", lat)
                .queryParam("longitude", lon)
                .queryParam("current_weather", true)
                .queryParam("temperature_unit", tempUnit)
                .build()
                .toUriString();

        return restClient.get()
                .uri(weatherUrl)
                .retrieve()
                .body(String.class);
    }
}
