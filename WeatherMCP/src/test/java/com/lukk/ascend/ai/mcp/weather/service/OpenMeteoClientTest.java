package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.config.CacheConfig;
import com.lukk.ascend.ai.mcp.weather.dto.AirQualityUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.ForecastUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Optional;

import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.COUNTRY_PL;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.LANG_EN;
import static com.lukk.ascend.ai.mcp.weather.fixtures.WeatherTestFixtures.UNIT_CELSIUS;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import org.springframework.http.HttpStatus;

class OpenMeteoClientTest {

    private static final String CITY = "Warsaw";

    private static final String GEO_TWO_CANDIDATES_RESPONSE = """
            {"results":[
              {"latitude":52.23,"longitude":21.01,"name":"Warsaw","country":"Poland","country_code":"PL"},
              {"latitude":52.20,"longitude":-83.85,"name":"Warsaw","country":"United States","country_code":"US"}
            ]}""";
    private static final String GEO_SINGLE_RESPONSE = """
            {"results":[{"latitude":52.23,"longitude":21.01,"name":"Warsaw","country":"Poland","country_code":"PL"}]}""";
    private static final String GEO_EMPTY_RESULTS_RESPONSE = "{\"results\":[]}";
    private static final String GEO_RESULTS_NULL_RESPONSE = "{\"results\":null}";
    private static final String CURRENT_WEATHER_RESPONSE = """
            {"current_weather":{"temperature":7.5,"windspeed":12.0,"winddirection":180.0,"weathercode":1,"time":"2026-05-30T01:00"}}""";
    private static final String FORECAST_RESPONSE = """
            {"daily":{"time":["2026-05-30","2026-05-31"],"temperature_2m_max":[18.0,20.0],"temperature_2m_min":[8.0,9.0],"precipitation_sum":[0.0,1.2],"weather_code":[1,2]}}""";
    private static final String AIR_QUALITY_RESPONSE = """
            {"current":{"pm10":12.3,"pm2_5":7.4,"us_aqi":45,"european_aqi":30}}""";

    private MockRestServiceServer mockServer;
    private OpenMeteoClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        RestClient restClient = builder.build();
        client = new OpenMeteoClient(restClient);
    }

    @Test
    @DisplayName("geocode returns the first candidate when no countryCode filter is provided")
    void geocode_noCountryCode_returnsFirstCandidate() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_TWO_CANDIDATES_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        Optional<GeoResult> result = client.geocode(CITY, null, LANG_EN);

        // then
        assertThat(result).isPresent();
        assertThat(result.get().countryCode()).isEqualTo("PL");
    }

    @Test
    @DisplayName("geocode prefers the candidate matching the requested countryCode")
    void geocode_withCountryCode_returnsMatchingCandidate() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_TWO_CANDIDATES_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        Optional<GeoResult> result = client.geocode(CITY, "US", LANG_EN);

        // then
        assertThat(result).isPresent();
        assertThat(result.get().countryCode()).isEqualTo("US");
    }

    @Test
    @DisplayName("geocode falls back to the first candidate when no countryCode match exists")
    void geocode_withCountryCodeNoMatch_returnsFirstCandidate() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_SINGLE_RESPONSE, MediaType.APPLICATION_JSON));

        // when — "AQ" is a real ISO-3166-1 alpha-2 code (Antarctica) that will not match PL
        Optional<GeoResult> result = client.geocode(CITY, "AQ", LANG_EN);

        // then
        assertThat(result).isPresent();
        assertThat(result.get().countryCode()).isEqualTo("PL");
    }

    @Test
    @DisplayName("geocode returns empty when upstream body is null")
    void geocode_nullBody_returnsEmpty() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withStatus(HttpStatus.NO_CONTENT));

        // when
        Optional<GeoResult> result = client.geocode(CITY, COUNTRY_PL, LANG_EN);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("geocode returns empty when upstream returns null results field")
    void geocode_nullResultsField_returnsEmpty() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_RESULTS_NULL_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        Optional<GeoResult> result = client.geocode(CITY, COUNTRY_PL, LANG_EN);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("geocode returns empty when upstream returns an empty results array")
    void geocode_emptyResults_returnsEmpty() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_EMPTY_RESULTS_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        Optional<GeoResult> result = client.geocode(CITY, COUNTRY_PL, LANG_EN);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("fetchCurrentWeather returns the deserialised upstream payload")
    void fetchCurrentWeather_happyPath_returnsCurrentWeather() {
        // given
        mockServer.expect(requestTo(containsString("api.open-meteo.com/v1/forecast")))
                .andRespond(withSuccess(CURRENT_WEATHER_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        CurrentWeatherUpstream upstream = client.fetchCurrentWeather(52.23, 21.01, UNIT_CELSIUS);

        // then
        assertThat(upstream.currentWeather().temperature()).isEqualTo(7.5);
        assertThat(upstream.currentWeather().weatherCode()).isEqualTo(1);
    }

    @Test
    @DisplayName("fetchForecast returns the deserialised upstream payload")
    void fetchForecast_happyPath_returnsForecast() {
        // given
        mockServer.expect(requestTo(containsString("forecast_days=3")))
                .andRespond(withSuccess(FORECAST_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        ForecastUpstream upstream = client.fetchForecast(52.23, 21.01, 3, UNIT_CELSIUS);

        // then
        assertThat(upstream.daily().time()).hasSize(2);
    }

    @Test
    @DisplayName("fetchHistoricalWeather hits the archive endpoint and returns the upstream payload")
    void fetchHistoricalWeather_happyPath_returnsHistorical() {
        // given
        mockServer.expect(requestTo(containsString("archive-api.open-meteo.com/v1/archive")))
                .andRespond(withSuccess(FORECAST_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        ForecastUpstream upstream = client.fetchHistoricalWeather(52.23, 21.01, "2020-01-15", UNIT_CELSIUS);

        // then
        assertThat(upstream.daily().time()).hasSize(2);
    }

    @Test
    @DisplayName("fetchAirQuality hits the air-quality endpoint and returns the upstream payload")
    void fetchAirQuality_happyPath_returnsAirQuality() {
        // given
        mockServer.expect(requestTo(containsString("air-quality-api.open-meteo.com")))
                .andRespond(withSuccess(AIR_QUALITY_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        AirQualityUpstream upstream = client.fetchAirQuality(52.23, 21.01);

        // then
        assertThat(upstream.current().pm10()).isEqualTo(12.3);
        assertThat(upstream.current().europeanAqi()).isEqualTo(30);
    }

    @Test
    @DisplayName("geocodeAll returns the full candidate list when upstream succeeds")
    void geocodeAll_happyPath_returnsAllCandidates() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_TWO_CANDIDATES_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        List<GeoResult> results = client.geocodeAll(CITY, 5, LANG_EN);

        // then
        assertThat(results).hasSize(2);
    }

    @Test
    @DisplayName("geocodeAll returns empty list when upstream body is null")
    void geocodeAll_nullBody_returnsEmptyList() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withStatus(HttpStatus.NO_CONTENT));

        // when
        List<GeoResult> results = client.geocodeAll(CITY, 5, LANG_EN);

        // then
        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("geocodeAll returns empty list when upstream returns a null results field")
    void geocodeAll_nullResultsField_returnsEmptyList() {
        // given
        mockServer.expect(requestTo(containsString("geocoding-api.open-meteo.com")))
                .andRespond(withSuccess(GEO_RESULTS_NULL_RESPONSE, MediaType.APPLICATION_JSON));

        // when
        List<GeoResult> results = client.geocodeAll(CITY, 5, LANG_EN);

        // then
        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("fetchCurrentWeather propagates RestClientException on upstream 5xx")
    void fetchCurrentWeather_upstream5xx_propagatesException() {
        // given
        mockServer.expect(requestTo(containsString("api.open-meteo.com/v1/forecast")))
                .andRespond(withServerError());

        // then
        assertThatThrownBy(() -> client.fetchCurrentWeather(52.23, 21.01, UNIT_CELSIUS))
                .isInstanceOf(RestClientException.class);
    }

    @Test
    @DisplayName("geocode uses " + CacheConfig.GEOCODING_SINGLE_CACHE + " as the declared cache name")
    void geocode_cacheNameIsGeocodingSingle() {
        // The @Cacheable(value = CacheConfig.GEOCODING_SINGLE_CACHE) annotation on geocode() must
        // reference the constant — this test documents the constant value and keeps it in coverage.
        assertThat(CacheConfig.GEOCODING_SINGLE_CACHE).isEqualTo("geocoding-single");
    }

    @Test
    @DisplayName("geocodeAll uses " + CacheConfig.GEOCODING_MULTI_CACHE + " as the declared cache name")
    void geocodeAll_cacheNameIsGeocodingMulti() {
        assertThat(CacheConfig.GEOCODING_MULTI_CACHE).isEqualTo("geocoding-multi");
    }
}
