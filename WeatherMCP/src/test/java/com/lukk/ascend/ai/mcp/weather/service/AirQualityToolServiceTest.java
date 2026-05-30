package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.AirQualityResult;
import com.lukk.ascend.ai.mcp.weather.dto.AirQualityUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
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
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.WARSAW;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AirQualityToolServiceTest {

    private static final AirQualityUpstream.Current CURRENT = new AirQualityUpstream.Current(12.5, 8.3, 42, 30);

    @Mock
    private OpenMeteoClient client;

    @InjectMocks
    private WeatherToolService service;

    @Test
    @DisplayName("returns ok result with pm10, pm25, usAqi, europeanAqi when upstream succeeds")
    void getAirQuality_happyPath_returnsOkWithAllFields() {
        // given
        AirQualityUpstream upstream = new AirQualityUpstream(52.23, 21.01, CURRENT);
        when(client.geocode(CITY_WARSAW, COUNTRY_PL, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchAirQuality(WARSAW.latitude(), WARSAW.longitude())).thenReturn(upstream);

        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, COUNTRY_PL, LANG_EN);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.OK);
        assertThat(result.location().name()).isEqualTo("Warsaw");
        assertThat(result.location().countryCode()).isEqualTo("PL");
        assertThat(result.pm10()).isEqualTo(12.5);
        assertThat(result.pm25()).isEqualTo(8.3);
        assertThat(result.usAqi()).isEqualTo(42);
        assertThat(result.europeanAqi()).isEqualTo(30);
        assertThat(result.source()).isEqualTo("open-meteo");
    }

    @Test
    @DisplayName("returns city_not_found when geocoder returns no match")
    void getAirQuality_geocodeEmpty_returnsCityNotFound() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.empty());

        // when
        AirQualityResult result = service.getAirQuality("Atlantis", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        assertThat(result.requestedQuery()).isEqualTo("Atlantis");
        verify(client, never()).fetchAirQuality(anyDouble(), anyDouble());
    }

    @Test
    @DisplayName("returns city_not_found when geocoded location is missing coordinates")
    void getAirQuality_nullCoordinates_returnsCityNotFound() {
        // given
        GeoResult missingCoords = new GeoResult(null, null, "Phantom", "Nowhere", "US");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingCoords));

        // when
        AirQualityResult result = service.getAirQuality("Phantom", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchAirQuality(anyDouble(), anyDouble());
    }

    @Test
    @DisplayName("returns invalid_input when city is blank")
    void getAirQuality_blankCity_returnsInvalidInput() {
        // when
        AirQualityResult result = service.getAirQuality("   ", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("returns invalid_input when country code is not 2 letters")
    void getAirQuality_invalidCountryCode_returnsInvalidInput() {
        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, "POL", null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }

    @Test
    @DisplayName("uppercases countryCode before passing to geocoder")
    void getAirQuality_lowercaseCountryCode_normalisedToUppercase() {
        // given
        when(client.geocode(CITY_WARSAW, "PL", LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getAirQuality(CITY_WARSAW, "pl", null);

        // then
        verify(client).geocode(CITY_WARSAW, "PL", LANG_EN);
    }

    @Test
    @DisplayName("defaults to en when language is unrecognised")
    void getAirQuality_unknownLanguage_defaultsToEn() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.empty());

        // when
        service.getAirQuality(CITY_WARSAW, null, "zz");

        // then
        verify(client).geocode(CITY_WARSAW, null, LANG_EN);
    }

    @Test
    @DisplayName("returns upstream_unavailable when geocoder throws RestClientException")
    void getAirQuality_restClientExceptionOnGeocode_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(anyString(), any(), anyString())).thenThrow(new RestClientException("boom"));

        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when air quality endpoint throws RestClientException")
    void getAirQuality_restClientExceptionOnAirQuality_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchAirQuality(anyDouble(), anyDouble())).thenThrow(new RestClientException("boom"));

        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns upstream_unavailable when upstream payload has null current block")
    void getAirQuality_upstreamMissingCurrentBlock_returnsUpstreamUnavailable() {
        // given
        AirQualityUpstream upstream = new AirQualityUpstream(52.23, 21.01, null);
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchAirQuality(anyDouble(), anyDouble())).thenReturn(upstream);

        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns city_not_found when only longitude coordinate is null")
    void getAirQuality_nullLongitudeOnly_returnsCityNotFound() {
        // given
        GeoResult missingLon = new GeoResult(52.23, null, "Partial", "Land", "PL");
        when(client.geocode(anyString(), any(), anyString())).thenReturn(Optional.of(missingLon));

        // when
        AirQualityResult result = service.getAirQuality("Partial", null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.CITY_NOT_FOUND);
        verify(client, never()).fetchAirQuality(anyDouble(), anyDouble());
    }

    @Test
    @DisplayName("returns upstream_unavailable when fetchAirQuality returns null")
    void getAirQuality_upstreamReturnsNull_returnsUpstreamUnavailable() {
        // given
        when(client.geocode(CITY_WARSAW, null, LANG_EN)).thenReturn(Optional.of(WARSAW));
        when(client.fetchAirQuality(anyDouble(), anyDouble())).thenReturn(null);

        // when
        AirQualityResult result = service.getAirQuality(CITY_WARSAW, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.UPSTREAM_UNAVAILABLE);
    }

    @Test
    @DisplayName("returns invalid_input when city is null")
    void getAirQuality_nullCity_returnsInvalidInput() {
        // when
        AirQualityResult result = service.getAirQuality(null, null, null);

        // then
        assertThat(result.status()).isEqualTo(WeatherToolStatus.INVALID_INPUT);
        verify(client, never()).geocode(anyString(), any(), anyString());
    }
}
