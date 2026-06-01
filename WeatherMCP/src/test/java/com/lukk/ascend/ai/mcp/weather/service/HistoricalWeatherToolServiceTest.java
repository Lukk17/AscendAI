package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.ForecastUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import com.lukk.ascend.ai.mcp.weather.dto.HistoricalWeatherResult;
import com.lukk.ascend.ai.mcp.weather.dto.WeatherToolStatus;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClientException;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.CITY_WARSAW;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.COUNTRY_PL;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.LANG_EN;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.UNIT_CELSIUS;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.WARSAW;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class HistoricalWeatherToolServiceTest {

    private static final String PAST_DATE = "2020-01-15";

    private static final ForecastUpstream.Daily DAILY = new ForecastUpstream.Daily(
            List.of(PAST_DATE),
            List.of(15.0),
            List.of(5.0),
            List.of(1.2),
            List.of(3)
    );

    @Mock
    private OpenMeteoClient client;

    @InjectMocks
    private WeatherToolService service;

    @Test
    @DisplayName("returns ok result with single day entry when upstream succeeds")
    void getHistoricalWeather_happyPath_returnsOkWithSingleDay() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, COUNTRY_PL, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(WARSAW.latitude(), WARSAW.longitude(), PAST_DATE, UNIT_CELSIUS))
                .thenReturn(upstream);

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, COUNTRY_PL, PAST_DATE, UNIT_CELSIUS, LANG_EN);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.location().name()).isEqualTo("Warsaw");
        assertThat(result.location().countryCode()).isEqualTo("PL");
        assertThat(result.day().date()).isEqualTo(PAST_DATE);
        assertThat(result.day().maxTemp()).isEqualTo(15.0);
        assertThat(result.day().minTemp()).isEqualTo(5.0);
        assertThat(result.day().precipitationSum()).isEqualTo(1.2);
        assertThat(result.day().weatherCode()).isEqualTo(3);
        assertThat(result.temperatureUnit()).isEqualTo(UNIT_CELSIUS);
        assertThat(result.source()).isEqualTo("open-meteo");
    }

    @Test
    @DisplayName("returns city_not_found when geocoder returns no match")
    void getHistoricalWeather_geocodeEmpty_returnsCityNotFound() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.empty());

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather("Atlantis", null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        assertThat(result.requestedQuery()).isEqualTo("Atlantis");
        verify(client, never()).fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString());
    }

    @Test
    @DisplayName("returns city_not_found when geocoded location is missing coordinates")
    void getHistoricalWeather_nullCoordinates_returnsCityNotFound() {
        // given
        GeoResult missingCoords = new GeoResult(null, null, "Phantom", "Nowhere", "US");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingCoords));

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather("Phantom", null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when city is blank")
    void getHistoricalWeather_blankCity_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather("   ", null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when country code is not 2 letters")
    void getHistoricalWeather_invalidCountryCode_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, "POL", PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when date is blank")
    void getHistoricalWeather_blankDate_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, "   ", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("blank");
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when date format is not yyyy-MM-dd")
    void getHistoricalWeather_malformedDate_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, "30-05-2024", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("format");
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when date is today")
    void getHistoricalWeather_today_returnsInvalidInput() {
        // given
        String today = LocalDate.now().toString();

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, today, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("past");
    }

    @Test
    @DisplayName("returns invalid_input when date is in the future")
    void getHistoricalWeather_futureDate_returnsInvalidInput() {
        // given
        String future = LocalDate.now().plusDays(1).toString();

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, future, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("past");
    }

    @Test
    @DisplayName("returns invalid_input when date is older than 80 years")
    void getHistoricalWeather_tooOldDate_returnsInvalidInput() {
        // given
        String ancient = LocalDate.now().minusYears(InputValidator.MAX_HISTORICAL_YEARS + 1).toString();

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, ancient, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("80 years");
    }

    @Test
    @DisplayName("uppercases countryCode before passing to geocoder")
    void getHistoricalWeather_lowercaseCountryCode_normalisedToUppercase() {
        // given
        when(client.geocode(CITY_WARSAW, "PL", LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getHistoricalWeather(CITY_WARSAW, "pl", PAST_DATE, null, null);

        // then
        verify(client).geocode(CITY_WARSAW, "PL", LANG_EN);
    }

    @Test
    @DisplayName("defaults to celsius when unit is unrecognised")
    void getHistoricalWeather_unknownUnit_defaultsToCelsius() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(WARSAW.latitude(), WARSAW.longitude(), PAST_DATE, UNIT_CELSIUS))
                .thenReturn(upstream);

        // when
        service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, "kelvin", null);

        // then
        verify(client).fetchHistoricalWeather(WARSAW.latitude(), WARSAW.longitude(), PAST_DATE, UNIT_CELSIUS);
    }

    @Test
    @DisplayName("defaults to en when language is unrecognised")
    void getHistoricalWeather_unknownLanguage_defaultsToEn() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, "zz");

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("returns upstream_unavailable when geocoder throws RestClientException")
    void getHistoricalWeather_restClientExceptionOnGeocode_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when archive endpoint throws RestClientException")
    void getHistoricalWeather_restClientExceptionOnArchive_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString()))
                .thenThrow(new RestClientException("boom"));

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when upstream payload has null daily block")
    void getHistoricalWeather_upstreamMissingDailyBlock_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, null);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString())).thenReturn(upstream);

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns city_not_found when only longitude coordinate is null")
    void getHistoricalWeather_nullLongitudeOnly_returnsCityNotFound() {
        // given
        GeoResult missingLon = new GeoResult(52.23, null, "Partial", "Land", "PL");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingLon));

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather("Partial", null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when fetchHistoricalWeather returns null")
    void getHistoricalWeather_upstreamReturnsNull_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString())).thenReturn(null);

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when daily block has empty time list")
    void getHistoricalWeather_upstreamDailyHasEmptyTimeList_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream.Daily emptyTimes = new ForecastUpstream.Daily(
                List.of(), List.of(), List.of(), List.of(), List.of()
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, emptyTimes);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString())).thenReturn(upstream);

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
        assertThat(result.message()).isNotBlank();
    }

    @Test
    @DisplayName("returns invalid_input when date is null")
    void getHistoricalWeather_nullDate_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("blank");
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when city is null")
    void getHistoricalWeather_nullCity_returnsInvalidInput() {
        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(null, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when daily block has null time list")
    void getHistoricalWeather_upstreamDailyHasNullTimeList_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream.Daily nullTimes = new ForecastUpstream.Daily(
                null, List.of(15.0), List.of(5.0), List.of(1.2), List.of(3)
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, nullTimes);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchHistoricalWeather(anyDouble(), anyDouble(), anyString(), anyString())).thenReturn(upstream);

        // when
        HistoricalWeatherResult result = service.getHistoricalWeather(CITY_WARSAW, null, PAST_DATE, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }
}
