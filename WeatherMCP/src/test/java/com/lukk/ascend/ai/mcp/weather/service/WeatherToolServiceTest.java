package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.GeoResponse;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClient;

import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.contains;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class WeatherToolServiceTest {

    @Mock
    private RestClient.Builder restClientBuilder;

    @Mock
    private RestClient restClient;

    @Mock
    private RestClient.RequestHeadersUriSpec requestHeadersUriSpec;

    @Mock
    private RestClient.RequestHeadersSpec requestHeadersSpec;

    @Mock
    private RestClient.ResponseSpec responseSpec;

    private WeatherToolService weatherToolService;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        when(restClientBuilder.build()).thenReturn(restClient);
        weatherToolService = new WeatherToolService(restClientBuilder);


        when(restClient.get()).thenReturn(requestHeadersUriSpec);
        when(requestHeadersUriSpec.uri(anyString())).thenReturn(requestHeadersSpec);
        when(requestHeadersSpec.retrieve()).thenReturn(responseSpec);
    }

    @Test
    void getCurrentWeather_ShouldReturnWeather_WhenCityFound() {
        // given
        String city = "London";
        // Mock Geo response
        GeoResult geoResult = new GeoResult(51.51, -0.13, "London", "UK");
        GeoResponse geoResponse = new GeoResponse(List.of(geoResult));

        // Mock Weather response
        String weatherResponse = "Current weather: 15C";

        // Sequential definitions handle differing return types (GeoResponse vs String)
        // for the two API calls.
        when(responseSpec.body(GeoResponse.class)).thenReturn(geoResponse);
        when(responseSpec.body(String.class)).thenReturn(weatherResponse);

        // when
        String result = weatherToolService.getCurrentWeather(city, "celsius", "en");

        // then
        assertEquals(weatherResponse, result);
    }

    @Test
    void getCurrentWeather_ShouldReturnNotFound_WhenGeoResponseIsNull() {
        // given
        String city = "UnknownCity";
        when(responseSpec.body(GeoResponse.class)).thenReturn(null);

        // when
        String result = weatherToolService.getCurrentWeather(city, null, null);

        // then
        assertEquals("City not found: " + city, result);
    }

    @Test
    void getCurrentWeather_ShouldReturnNotFound_WhenGeoResultsEmpty() {
        // given
        String city = "EmptyCity";
        GeoResponse geoResponse = new GeoResponse(Collections.emptyList());
        when(responseSpec.body(GeoResponse.class)).thenReturn(geoResponse);

        // when
        String result = weatherToolService.getCurrentWeather(city, "celsius", "en");

        // then
        assertEquals("City not found: " + city, result);
    }

    @Test
    void getCurrentWeather_ShouldHandleUnitParam() {
        // given
        String city = "New York";
        // Geo response
        GeoResult geoResult = new GeoResult(40.71, -74.01, "New York", "USA");
        GeoResponse geoResponse = new GeoResponse(List.of(geoResult));
        String weatherResponse = "Weather in F";

        when(responseSpec.body(GeoResponse.class)).thenReturn(geoResponse);
        when(responseSpec.body(String.class)).thenReturn(weatherResponse);

        // when
        weatherToolService.getCurrentWeather(city, "fahrenheit", "en");

        // then
        verify(requestHeadersUriSpec, atLeastOnce()).uri(contains("temperature_unit=fahrenheit"));
    }

    @Test
    void getCurrentWeather_ShouldDefaultToCelsius_WhenUnitInvalid() {
        // given
        String city = "City";
        GeoResult geoResult = new GeoResult(10.0, 10.0, "City", "Country");
        GeoResponse geoResponse = new GeoResponse(List.of(geoResult));
        String weatherResponse = "Weather in C";

        when(responseSpec.body(GeoResponse.class)).thenReturn(geoResponse);
        when(responseSpec.body(String.class)).thenReturn(weatherResponse);

        // when
        weatherToolService.getCurrentWeather(city, "INVALID_UNIT", "en");

        // then
        verify(requestHeadersUriSpec, atLeastOnce()).uri(contains("temperature_unit=celsius"));
    }
}
