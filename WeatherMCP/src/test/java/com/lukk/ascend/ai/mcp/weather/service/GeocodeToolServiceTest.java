package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.GeocodeResult;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import com.lukk.ascend.ai.mcp.weather.dto.WeatherToolStatus;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.web.client.RestClientException;

import java.util.List;

import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.LANG_EN;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class GeocodeToolServiceTest {

    private static final String QUERY_PARIS = "Paris";
    private static final GeoResult PARIS_FR = new GeoResult(48.85, 2.35, "Paris", "France", "FR");
    private static final GeoResult PARIS_US = new GeoResult(33.66, -95.55, "Paris", "United States", "US");

    @Mock
    private OpenMeteoClient client;

    @InjectMocks
    private WeatherToolService service;

    @Test
    @DisplayName("returns ok result with candidate list when upstream returns multiple matches")
    void geocode_happyPath_returnsOkWithCandidates() {
        // given
        when(client.geocodeAll(QUERY_PARIS, WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN)).thenReturn(List.of(PARIS_FR, PARIS_US));

        // when
        GeocodeResult result = service.geocode(QUERY_PARIS, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.candidates()).hasSize(2);
        assertThat(result.candidates().getFirst().name()).isEqualTo("Paris");
        assertThat(result.candidates().getFirst().countryCode()).isEqualTo("FR");
        assertThat(result.candidates().getLast().countryCode()).isEqualTo("US");
        assertThat(result.source()).isEqualTo("open-meteo");
    }

    @Test
    @DisplayName("defaults to limit 5 when limit parameter is null")
    void geocode_nullLimit_defaultsTo5() {
        // given
        when(client.geocodeAll(QUERY_PARIS, WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN)).thenReturn(List.of(PARIS_FR));

        // when
        service.geocode(QUERY_PARIS, null, null);

        // then
        verify(client).geocodeAll(QUERY_PARIS, WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN);
    }

    @Test
    @DisplayName("returns no_results when geocoder returns empty list")
    void geocode_emptyResults_returnsNoResults() {
        // given
        when(client.geocodeAll(anyString(), anyInt(), anyString())).thenReturn(List.of());

        // when
        GeocodeResult result = service.geocode("Zzzbogtown", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.NO_RESULTS);
        assertThat(result.requestedQuery()).isEqualTo("Zzzbogtown");
        verify(client).geocodeAll("Zzzbogtown", WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN);
    }

    @Test
    @DisplayName("returns invalid_input when query is blank")
    void geocode_blankQuery_returnsInvalidInput() {
        // when
        GeocodeResult result = service.geocode("   ", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocodeAll(anyString(), anyInt(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when limit is 0")
    void geocode_limitZero_returnsInvalidInput() {
        // when
        GeocodeResult result = service.geocode(QUERY_PARIS, 0, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("limit");
        verify(client, never()).geocodeAll(anyString(), anyInt(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when limit exceeds 10")
    void geocode_limit11_returnsInvalidInput() {
        // when
        GeocodeResult result = service.geocode(QUERY_PARIS, WeatherToolService.MAX_GEOCODE_LIMIT + 1, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        assertThat(result.message()).containsIgnoringCase("limit");
        verify(client, never()).geocodeAll(anyString(), anyInt(), anyString());
    }

    @Test
    @DisplayName("accepts limit boundary values 1 and 10")
    void geocode_limitBoundaryValues_accepted() {
        // given
        when(client.geocodeAll(QUERY_PARIS, WeatherToolService.MIN_GEOCODE_LIMIT, LANG_EN)).thenReturn(List.of(PARIS_FR));
        when(client.geocodeAll(QUERY_PARIS, WeatherToolService.MAX_GEOCODE_LIMIT, LANG_EN)).thenReturn(List.of(PARIS_FR));

        // when
        GeocodeResult resultOne = service.geocode(QUERY_PARIS, WeatherToolService.MIN_GEOCODE_LIMIT, null);
        GeocodeResult resultTen = service.geocode(QUERY_PARIS, WeatherToolService.MAX_GEOCODE_LIMIT, null);

        // then
        assertThat(resultOne.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(resultTen.status()).isEqualTo(WeatherToolStatus.OK);
    }

    @Test
    @DisplayName("defaults to en when language is unrecognised")
    void geocode_unknownLanguage_defaultsToEn() {
        // given
        when(client.geocodeAll(QUERY_PARIS, WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN)).thenReturn(List.of(PARIS_FR));

        // when
        service.geocode(QUERY_PARIS, null, "zz");

        // then
        verify(client).geocodeAll(QUERY_PARIS, WeatherToolService.DEFAULT_GEOCODE_LIMIT, LANG_EN);
    }

    @Test
    @DisplayName("returns upstream_unavailable when geocodeAll throws RestClientException")
    void geocode_restClientException_returnsUpstreamUnavailable() {
        // given
        when(client.geocodeAll(anyString(), anyInt(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        GeocodeResult result = service.geocode(QUERY_PARIS, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns invalid_input when query is null")
    void geocode_nullQuery_returnsInvalidInput() {
        // when
        GeocodeResult result = service.geocode(null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocodeAll(anyString(), anyInt(), anyString());
    }

    @Test
    @DisplayName("error message says Query not City when query validation fails in geocode tool")
    void geocode_blankQuery_errorMessageSaysQuery() {
        // when
        GeocodeResult result = service.geocode("   ", null, null);

        // then
        assertThat(result.message()).containsIgnoringCase("Query");
    }
}
