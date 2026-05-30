package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.config.CacheConfig;
import com.lukk.ascend.ai.mcp.weather.config.RestClientConfig;
import com.lukk.ascend.ai.mcp.weather.config.WeatherApiEndpoints;
import com.lukk.ascend.ai.mcp.weather.dto.AirQualityUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.ForecastUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResponse;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.List;
import java.util.Optional;

@Component
@Slf4j
public class OpenMeteoClient {

    private static final String GEOCODE_KEY = "T(com.lukk.ascend.ai.mcp.weather.service.InputValidator).normaliseCacheKey(#city) + '|' + #countryCode + '|' + #language";
    private static final String GEOCODE_ALL_KEY = "T(com.lukk.ascend.ai.mcp.weather.service.InputValidator).normaliseCacheKey(#query) + '|' + #limit + '|' + #language";

    private final RestClient restClient;

    public OpenMeteoClient(@Qualifier(RestClientConfig.OPEN_METEO_BEAN_NAME) RestClient openMeteoRestClient) {
        this.restClient = openMeteoRestClient;
    }

    @Cacheable(value = CacheConfig.GEOCODING_SINGLE_CACHE, sync = true, key = GEOCODE_KEY)
    public Optional<GeoResult> geocode(String city, String countryCode, String language) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.GEOCODING)
                .queryParam("name", city)
                .queryParam("count", 5)
                .queryParam("language", language)
                .queryParam("format", "json")
                .build()
                .toUriString();

        GeoResponse response = restClient.get()
                .uri(url)
                .retrieve()
                .body(GeoResponse.class);

        if (response == null || response.results() == null || response.results().isEmpty()) {
            return Optional.empty();
        }

        return pickBestMatch(response.results(), countryCode);
    }

    @Cacheable(value = CacheConfig.CURRENT_WEATHER_CACHE, sync = true)
    public CurrentWeatherUpstream fetchCurrentWeather(double latitude, double longitude, String unit) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.FORECAST)
                .queryParam("latitude", latitude)
                .queryParam("longitude", longitude)
                .queryParam("current_weather", true)
                .queryParam("temperature_unit", unit)
                .build()
                .toUriString();

        return restClient.get()
                .uri(url)
                .retrieve()
                .body(CurrentWeatherUpstream.class);
    }

    @Cacheable(value = CacheConfig.FORECAST_CACHE, sync = true)
    public ForecastUpstream fetchForecast(double latitude, double longitude, int days, String unit) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.FORECAST)
                .queryParam("latitude", latitude)
                .queryParam("longitude", longitude)
                .queryParam("daily", "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code")
                .queryParam("forecast_days", days)
                .queryParam("temperature_unit", unit)
                .build()
                .toUriString();

        return restClient.get()
                .uri(url)
                .retrieve()
                .body(ForecastUpstream.class);
    }

    @Cacheable(value = CacheConfig.HISTORICAL_WEATHER_CACHE, sync = true)
    public ForecastUpstream fetchHistoricalWeather(double latitude, double longitude, String date, String unit) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.ARCHIVE)
                .queryParam("latitude", latitude)
                .queryParam("longitude", longitude)
                .queryParam("start_date", date)
                .queryParam("end_date", date)
                .queryParam("daily", "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code")
                .queryParam("temperature_unit", unit)
                .build()
                .toUriString();

        return restClient.get()
                .uri(url)
                .retrieve()
                .body(ForecastUpstream.class);
    }

    @Cacheable(value = CacheConfig.AIR_QUALITY_CACHE, sync = true)
    public AirQualityUpstream fetchAirQuality(double latitude, double longitude) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.AIR_QUALITY)
                .queryParam("latitude", latitude)
                .queryParam("longitude", longitude)
                .queryParam("current", "pm10,pm2_5,us_aqi,european_aqi")
                .build()
                .toUriString();

        return restClient.get()
                .uri(url)
                .retrieve()
                .body(AirQualityUpstream.class);
    }

    @Cacheable(value = CacheConfig.GEOCODING_MULTI_CACHE, sync = true, key = GEOCODE_ALL_KEY)
    public List<GeoResult> geocodeAll(String query, int limit, String language) {
        String url = UriComponentsBuilder.fromUriString(WeatherApiEndpoints.GEOCODING)
                .queryParam("name", query)
                .queryParam("count", limit)
                .queryParam("language", language)
                .queryParam("format", "json")
                .build()
                .toUriString();

        GeoResponse response = restClient.get()
                .uri(url)
                .retrieve()
                .body(GeoResponse.class);

        if (response == null || response.results() == null) {
            return List.of();
        }

        return response.results();
    }

    private static Optional<GeoResult> pickBestMatch(List<GeoResult> candidates, String countryCode) {
        if (countryCode == null) {
            return Optional.of(candidates.getFirst());
        }

        return candidates.stream()
                .filter(c -> countryCode.equalsIgnoreCase(c.countryCode()))
                .findFirst()
                .or(() -> Optional.of(candidates.getFirst()));
    }
}
