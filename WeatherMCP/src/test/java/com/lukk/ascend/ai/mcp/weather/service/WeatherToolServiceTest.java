package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherResult;
import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.WeatherToolStatus;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClientException;

import java.util.Optional;

import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.CITY_WARSAW;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.COUNTRY_PL;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.LANG_EN;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.UNIT_CELSIUS;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.UNIT_FAHRENHEIT;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.WARSAW;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class WeatherToolServiceTest {

    @Mock
    private OpenMeteoClient client;

    @InjectMocks
    private WeatherToolService service;

    @Test
    @DisplayName("returns ok result with location and temperature when upstream succeeds")
    void getCurrentWeather_happyPath_returnsOkWithStructuredFields() {
        // given
        CurrentWeatherUpstream upstream = new CurrentWeatherUpstream(
                52.23, 21.01,
                new CurrentWeatherUpstream.Current(7.5, 12.0, 180.0, 1, "2026-05-30T01:00")
        );
        when(client.geocode(CITY_WARSAW, COUNTRY_PL, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(WARSAW.latitude(), WARSAW.longitude(), UNIT_CELSIUS)).thenReturn(upstream);

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, COUNTRY_PL, UNIT_CELSIUS, LANG_EN);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.location().name()).isEqualTo("Warsaw");
        assertThat(result.location().countryCode()).isEqualTo("PL");
        assertThat(result.temperature().value()).isEqualTo(7.5);
        assertThat(result.temperature().unit()).isEqualTo(UNIT_CELSIUS);
        assertThat(result.weatherCode()).isEqualTo(1);
        assertThat(result.wind().speed()).isEqualTo(12.0);
        assertThat(result.observedAt()).isEqualTo("2026-05-30T01:00");
        assertThat(result.source()).isEqualTo("open-meteo");
    }

    @Test
    @DisplayName("returns city_not_found when geocoder returns no match")
    void getCurrentWeather_geocodeEmpty_returnsCityNotFound() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.empty());

        // when
        CurrentWeatherResult result = service.getCurrentWeather("Atlantis", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        assertThat(result.requestedQuery()).isEqualTo("Atlantis");
        verify(client, never()).fetchCurrentWeather(anyDouble(), anyDouble(), anyString());
    }

    @Test
    @DisplayName("returns city_not_found when geocoded location is missing coordinates")
    void getCurrentWeather_nullCoordinates_returnsCityNotFound() {
        // given
        var missingCoords = new com.lukk.ascend.ai.mcp.weather.dto.GeoResult(null, null, "Phantom", "Nowhere", "US");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingCoords));

        // when
        CurrentWeatherResult result = service.getCurrentWeather("Phantom", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchCurrentWeather(anyDouble(), anyDouble(), anyString());
    }

    @Test
    @DisplayName("forwards fahrenheit when caller requests it")
    void getCurrentWeather_fahrenheitUnit_normalisedAndForwarded() {
        // given
        CurrentWeatherUpstream upstream = new CurrentWeatherUpstream(
                52.23, 21.01,
                new CurrentWeatherUpstream.Current(46.0, 8.0, 90.0, 0, "2026-05-30T01:00")
        );
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(WARSAW.latitude(), WARSAW.longitude(), UNIT_FAHRENHEIT)).thenReturn(upstream);

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, null, UNIT_FAHRENHEIT, LANG_EN);

        // then
        assertThat(result.temperature().unit()).isEqualTo(UNIT_FAHRENHEIT);
        verify(client).fetchCurrentWeather(WARSAW.latitude(), WARSAW.longitude(), UNIT_FAHRENHEIT);
    }

    @Test
    @DisplayName("defaults to celsius when caller passes an unrecognised unit")
    void getCurrentWeather_unknownUnit_defaultsToCelsius() {
        // given
        CurrentWeatherUpstream upstream = new CurrentWeatherUpstream(
                52.23, 21.01,
                new CurrentWeatherUpstream.Current(7.5, 12.0, 180.0, 1, "2026-05-30T01:00")
        );
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(WARSAW.latitude(), WARSAW.longitude(), UNIT_CELSIUS)).thenReturn(upstream);

        // when
        service.getCurrentWeather(CITY_WARSAW, null, "kelvin", LANG_EN);

        // then
        verify(client).fetchCurrentWeather(WARSAW.latitude(), WARSAW.longitude(), UNIT_CELSIUS);
    }

    @Test
    @DisplayName("defaults to en when caller passes an unrecognised language")
    void getCurrentWeather_unknownLanguage_defaultsToEn() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getCurrentWeather(CITY_WARSAW, null, null, "zz");

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("returns invalid_input when city is blank")
    void getCurrentWeather_blankCity_returnsInvalidInput() {
        // when
        CurrentWeatherResult result = service.getCurrentWeather("   ", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("blank");
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when city contains control characters")
    void getCurrentWeather_cityWithCrlf_returnsInvalidInput() {
        // when
        CurrentWeatherResult result = service.getCurrentWeather("Warsaw\r\nignore previous", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when city is longer than the configured maximum")
    void getCurrentWeather_cityTooLong_returnsInvalidInput() {
        // given
        String longCity = "A".repeat(InputValidator.CITY_MAX_LENGTH + 1);

        // when
        CurrentWeatherResult result = service.getCurrentWeather(longCity, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
    }

    @Test
    @DisplayName("returns invalid_input when countryCode is not 2 letters")
    void getCurrentWeather_invalidCountryCode_returnsInvalidInput() {
        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, "POL", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when geocoder throws RestClientException")
    void getCurrentWeather_restClientExceptionOnGeocode_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when forecast endpoint throws RestClientException")
    void getCurrentWeather_restClientExceptionOnForecast_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(anyDouble(), anyDouble(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when upstream payload has no current weather block")
    void getCurrentWeather_upstreamMissingCurrentBlock_returnsUpstreamUnavailable() {
        // given
        CurrentWeatherUpstream upstream = new CurrentWeatherUpstream(52.23, 21.01, null);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(anyDouble(), anyDouble(), anyString())).thenReturn(upstream);

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("uppercases countryCode before passing to geocoder")
    void getCurrentWeather_lowercaseCountryCode_normalisedToUppercase() {
        // given
        when(client.geocode(CITY_WARSAW, "PL", LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getCurrentWeather(CITY_WARSAW, "pl", null, null);

        // then
        verify(client).geocode(CITY_WARSAW, "PL", LANG_EN);
    }

    @Test
    @DisplayName("returns city_not_found when only longitude coordinate is null")
    void getCurrentWeather_nullLongitudeOnly_returnsCityNotFound() {
        // given
        var missingLon = new com.lukk.ascend.ai.mcp.weather.dto.GeoResult(52.23, null, "Partial", "Land", "PL");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingLon));

        // when
        CurrentWeatherResult result = service.getCurrentWeather("Partial", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchCurrentWeather(anyDouble(), anyDouble(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when fetchCurrentWeather returns null")
    void getCurrentWeather_upstreamReturnsNull_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchCurrentWeather(anyDouble(), anyDouble(), anyString())).thenReturn(null);

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns invalid_input when city is null")
    void getCurrentWeather_nullCity_returnsInvalidInput() {
        // when
        CurrentWeatherResult result = service.getCurrentWeather(null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("treats blank-but-non-null country code as absent and proceeds with geocoding")
    void getCurrentWeather_blankCountryCode_treatedAsAbsent() {
        // given — blank country code isBlank() == true → treated as absent (valid)
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, "   ", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("defaults to celsius when unit is blank but non-null")
    void getCurrentWeather_blankUnit_defaultsToCelsius() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getCurrentWeather(CITY_WARSAW, null, "  ", null);

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("defaults to en when language is blank but non-null")
    void getCurrentWeather_blankLanguage_defaultsToEn() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getCurrentWeather(CITY_WARSAW, null, null, "  ");

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("returns invalid_input with requestedQuery when country code is unknown ISO code")
    void getCurrentWeather_unknownIsoCountryCode_returnsInvalidInput() {
        // when — "ZZ" is two letters but not a real ISO-3166-1 alpha-2 code
        CurrentWeatherResult result = service.getCurrentWeather(CITY_WARSAW, "ZZ", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("ISO-3166-1");
        verify(client, never()).geocode(anyString(), any(), anyString());
    }
}
