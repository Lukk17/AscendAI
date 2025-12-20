package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.GeoResponse;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

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

        String lang = (language != null && !language.isEmpty()) ? language : "en";
        GeoResponse geoResponse = fetchCoordinates(city, lang);

        if (geoResponse == null || geoResponse.results() == null || geoResponse.results().isEmpty()) {
            return "City not found: " + city;
        }

        GeoResult location = geoResponse.results().get(0);
        return fetchWeather(location.latitude(), location.longitude(), unit);
    }

    private GeoResponse fetchCoordinates(String city, String language) {
        String geoUrl = UriComponentsBuilder.fromUriString("https://geocoding-api.open-meteo.com/v1/search")
                .queryParam("name", city)
                .queryParam("count", 1)
                .queryParam("language", language)
                .queryParam("format", "json")
                .build()
                .toUriString();

        return restClient.get()
                .uri(geoUrl)
                .retrieve()
                .body(GeoResponse.class);
    }

    private String fetchWeather(double lat, double lon, String unit) {
        String tempUnit = (unit != null && unit.equalsIgnoreCase("fahrenheit")) ? "fahrenheit" : "celsius";
        String weatherUrl = UriComponentsBuilder.fromUriString("https://api.open-meteo.com/v1/forecast")
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
