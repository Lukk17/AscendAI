package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.ForecastResult;
import com.lukk.ascend.ai.mcp.weather.dto.ForecastUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.WeatherToolStatus;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClientException;

import java.util.List;
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
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ForecastToolServiceTest {

    private static final ForecastUpstream.Daily DAILY = new ForecastUpstream.Daily(
            List.of("2026-05-01", "2026-05-02"),
            List.of(18.5, 20.1),
            List.of(9.0, 11.0),
            List.of(2.5, 0.0),
            List.of(2, 1)
    );

    @Mock
    private OpenMeteoClient client;

    @InjectMocks
    private WeatherToolService service;

    @Test
    @DisplayName("returns ok result with forecast list when upstream succeeds")
    void getForecast_happyPath_returnsOkWithDailyList() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, COUNTRY_PL, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_CELSIUS)).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, COUNTRY_PL, null, UNIT_CELSIUS, LANG_EN);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.location().name()).isEqualTo("Warsaw");
        assertThat(result.location().countryCode()).isEqualTo("PL");
        assertThat(result.forecast()).hasSize(2);
        assertThat(result.forecast().getFirst().date()).isEqualTo("2026-05-01");
        assertThat(result.forecast().getFirst().maxTemp()).isEqualTo(18.5);
        assertThat(result.forecast().getFirst().minTemp()).isEqualTo(9.0);
        assertThat(result.forecast().getFirst().precipitationSum()).isEqualTo(2.5);
        assertThat(result.forecast().getFirst().weatherCode()).isEqualTo(2);
        assertThat(result.temperatureUnit()).isEqualTo(UNIT_CELSIUS);
        assertThat(result.source()).isEqualTo("open-meteo");
    }

    @Test
    @DisplayName("defaults to 7 days when days parameter is null")
    void getForecast_nullDays_defaultsTo7() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_CELSIUS)).thenReturn(upstream);

        // when
        service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        verify(client).fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_CELSIUS);
    }

    @Test
    @DisplayName("returns city_not_found when geocoder returns no match")
    void getForecast_geocodeEmpty_returnsCityNotFound() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.empty());

        // when
        ForecastResult result = service.getForecast("Atlantis", null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        assertThat(result.requestedQuery()).isEqualTo("Atlantis");
        verify(client, never()).fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString());
    }

    @Test
    @DisplayName("returns city_not_found when geocoded location is missing coordinates")
    void getForecast_nullCoordinates_returnsCityNotFound() {
        // given
        var missingCoords = new com.lukk.ascend.ai.mcp.weather.dto.GeoResult(null, null, "Phantom", "Nowhere", "US");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingCoords));

        // when
        ForecastResult result = service.getForecast("Phantom", null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when days is less than 1")
    void getForecast_daysZero_returnsInvalidInput() {
        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, 0, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("days");
    }

    @Test
    @DisplayName("returns invalid_input when days exceeds 16")
    void getForecast_days17_returnsInvalidInput() {
        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, WeatherToolService.MAX_FORECAST_DAYS + 1, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("days");
    }

    @Test
    @DisplayName("returns invalid_input when city is blank")
    void getForecast_blankCity_returnsInvalidInput() {
        // when
        ForecastResult result = service.getForecast("   ", null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when country code is not 2 letters")
    void getForecast_invalidCountryCode_returnsInvalidInput() {
        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, "POL", null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("uppercases countryCode before passing to geocoder")
    void getForecast_lowercaseCountryCode_normalisedToUppercase() {
        // given
        when(client.geocode(CITY_WARSAW, "PL", LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getForecast(CITY_WARSAW, "pl", null, null, null);

        // then
        verify(client).geocode(CITY_WARSAW, "PL", LANG_EN);
    }

    @Test
    @DisplayName("defaults to celsius when unit is unrecognised")
    void getForecast_unknownUnit_defaultsToCelsius() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_CELSIUS)).thenReturn(upstream);

        // when
        service.getForecast(CITY_WARSAW, null, null, "kelvin", null);

        // then
        verify(client).fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_CELSIUS);
    }

    @Test
    @DisplayName("defaults to en when language is unrecognised")
    void getForecast_unknownLanguage_defaultsToEn() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getForecast(CITY_WARSAW, null, null, null, "zz");

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("returns upstream_unavailable when geocoder throws RestClientException")
    void getForecast_restClientExceptionOnGeocode_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when forecast endpoint throws RestClientException")
    void getForecast_restClientExceptionOnForecast_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString()))
                .thenThrow(new RestClientException("boom"));

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when upstream payload has null daily block")
    void getForecast_upstreamMissingDailyBlock_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, null);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("forwards fahrenheit unit to fetchForecast")
    void getForecast_fahrenheitUnit_normalisedAndForwarded() {
        // given
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, DAILY);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_FAHRENHEIT)).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, UNIT_FAHRENHEIT, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.temperatureUnit()).isEqualTo(UNIT_FAHRENHEIT);
        verify(client).fetchForecast(WARSAW.latitude(), WARSAW.longitude(), WeatherToolService.DEFAULT_FORECAST_DAYS, UNIT_FAHRENHEIT);
    }

    @Test
    @DisplayName("returns city_not_found when only longitude coordinate is null")
    void getForecast_nullLongitudeOnly_returnsCityNotFound() {
        // given
        var missingLon = new com.lukk.ascend.ai.mcp.weather.dto.GeoResult(52.23, null, "Partial", "Land", "PL");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingLon));

        // when
        ForecastResult result = service.getForecast("Partial", null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when fetchForecast returns null")
    void getForecast_upstreamReturnsNull_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(null);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when daily block has empty time list")
    void getForecast_upstreamDailyHasEmptyTimeList_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream.Daily emptyTimes = new ForecastUpstream.Daily(
                List.of(), List.of(), List.of(), List.of(), List.of()
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, emptyTimes);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
        assertThat(result.message()).isNotBlank();
    }

    @Test
    @DisplayName("returns ok with null fields when sub-lists are shorter than the time list")
    void getForecast_subListsShorterThanTimeList_returnsOkWithNullFields() {
        // given — 2 dates but only 1 temperature max entry (index 1 is out of range)
        ForecastUpstream.Daily partial = new ForecastUpstream.Daily(
                List.of("2026-05-01", "2026-05-02"),
                List.of(18.5),
                List.of(),
                List.of(),
                List.of()
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, partial);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then — should succeed; the second entry has nulls for the missing values
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.forecast()).hasSize(2);
        assertThat(result.forecast().get(0).maxTemp()).isEqualTo(18.5);
        assertThat(result.forecast().get(1).maxTemp()).isNull();
    }

    @Test
    @DisplayName("returns invalid_input when city is null")
    void getForecast_nullCity_returnsInvalidInput() {
        // when
        ForecastResult result = service.getForecast(null, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns upstream_unavailable when daily block has null time list")
    void getForecast_upstreamDailyHasNullTimeList_returnsUpstreamUnavailable() {
        // given
        ForecastUpstream.Daily nullTimes = new ForecastUpstream.Daily(
                null, List.of(18.5), List.of(9.0), List.of(2.5), List.of(2)
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, nullTimes);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns ok with null fields when sub-lists are null")
    void getForecast_subListsNull_returnsOkWithNullFields() {
        // given — time has 1 entry, all sub-lists are null (testing getOrNull/getIntOrNull null-list branch)
        ForecastUpstream.Daily nullSublists = new ForecastUpstream.Daily(
                List.of("2026-05-01"), null, null, null, null
        );
        ForecastUpstream upstream = new ForecastUpstream(52.23, 21.01, nullSublists);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchForecast(anyDouble(), anyDouble(), anyInt(), anyString())).thenReturn(upstream);

        // when
        ForecastResult result = service.getForecast(CITY_WARSAW, null, null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.forecast()).hasSize(1);
        assertThat(result.forecast().getFirst().maxTemp()).isNull();
        assertThat(result.forecast().getFirst().minTemp()).isNull();
        assertThat(result.forecast().getFirst().precipitationSum()).isNull();
        assertThat(result.forecast().getFirst().weatherCode()).isNull();
    }
}
