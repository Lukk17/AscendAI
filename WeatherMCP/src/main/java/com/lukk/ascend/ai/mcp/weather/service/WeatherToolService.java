package com.lukk.ascend.ai.mcp.weather.service;

import com.lukk.ascend.ai.mcp.weather.dto.AirQualityResult;
import com.lukk.ascend.ai.mcp.weather.dto.AirQualityUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherResult;
import com.lukk.ascend.ai.mcp.weather.dto.CurrentWeatherUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.DailyForecast;
import com.lukk.ascend.ai.mcp.weather.dto.ForecastResult;
import com.lukk.ascend.ai.mcp.weather.dto.ForecastUpstream;
import com.lukk.ascend.ai.mcp.weather.dto.GeoResult;
import com.lukk.ascend.ai.mcp.weather.dto.GeocodeResult;
import com.lukk.ascend.ai.mcp.weather.dto.HistoricalWeatherResult;
import com.lukk.ascend.ai.mcp.weather.dto.ResolvedLocation;
import com.lukk.ascend.ai.mcp.weather.dto.Temperature;
import com.lukk.ascend.ai.mcp.weather.dto.Wind;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Optional;
import java.util.stream.IntStream;

@Service
@Slf4j
public class WeatherToolService {

    public static final int DEFAULT_FORECAST_DAYS = 7;
    public static final int MIN_FORECAST_DAYS = 1;
    public static final int MAX_FORECAST_DAYS = 16;
    public static final int DEFAULT_GEOCODE_LIMIT = 5;
    public static final int MIN_GEOCODE_LIMIT = 1;
    public static final int MAX_GEOCODE_LIMIT = 10;
    public static final String WIND_UNIT = "km/h";

    private final OpenMeteoClient client;

    public WeatherToolService(OpenMeteoClient client) {
        this.client = client;
    }

    @Tool(name = "weather.current",
            description = """
                    Get the current observed weather for a city via Open-Meteo. Returns a structured result with
                    resolved location (name, country, country code, lat/lon), temperature in the requested unit,
                    weather condition code, wind, observation time, and source. Use countryCode to disambiguate
                    common city names (e.g. 'Paris' with countryCode='US' for Paris, Texas).""")
    public CurrentWeatherResult getCurrentWeather(
            @ToolParam(description = "The name of a city, e.g. 'Warsaw'") String city,
            @ToolParam(description = "Optional ISO-3166-1 alpha-2 country code to disambiguate the city, e.g. 'PL'",
                    required = false) String countryCode,
            @ToolParam(description = "Temperature unit: 'celsius' (default) or 'fahrenheit'",
                    required = false) String unit,
            @ToolParam(description = "Open-Meteo language code (e.g. 'en', 'de', 'fr', 'it', 'es', 'pt', 'ru')",
                    required = false) String language) {

        String cityError = InputValidator.validateCity(city);
        if (cityError != null) {
            return CurrentWeatherResult.invalidInput(cityError, city);
        }

        String countryError = InputValidator.validateCountryCode(countryCode);
        if (countryError != null) {
            return CurrentWeatherResult.invalidInput(countryError, city);
        }

        String resolvedCountryCode = InputValidator.normaliseCountryCode(countryCode);
        String resolvedUnit = InputValidator.normaliseUnit(unit);
        String resolvedLanguage = InputValidator.normaliseLanguage(language);

        try {
            Optional<GeoResult> match = client.geocode(city, resolvedCountryCode, resolvedLanguage);
            if (match.isEmpty()) {
                return CurrentWeatherResult.cityNotFound(city);
            }

            GeoResult geo = match.get();
            if (geo.latitude() == null || geo.longitude() == null) {
                return CurrentWeatherResult.cityNotFound(city);
            }

            CurrentWeatherUpstream upstream = client.fetchCurrentWeather(geo.latitude(), geo.longitude(), resolvedUnit);

            return toResult(geo, upstream, resolvedUnit);
        } catch (RestClientException e) {
            log.warn("Open-Meteo upstream call failed for city={}", city, e);

            return CurrentWeatherResult.upstreamUnavailable();
        }
    }

    @Tool(name = "weather.forecast",
            description = """
                    Get a multi-day weather forecast for a city via Open-Meteo. Returns a list of daily entries, each
                    containing max/min temperature, precipitation sum, and weather code. 'days' controls how many days
                    ahead to forecast (1–16, default 7). Temperature unit defaults to celsius. Use countryCode to
                    disambiguate common city names.""")
    public ForecastResult getForecast(
            @ToolParam(description = "The name of a city, e.g. 'Warsaw'") String city,
            @ToolParam(description = "Optional ISO-3166-1 alpha-2 country code to disambiguate the city, e.g. 'PL'",
                    required = false) String countryCode,
            @ToolParam(description = "Number of forecast days, 1–16 (default 7)", required = false) Integer days,
            @ToolParam(description = "Temperature unit: 'celsius' (default) or 'fahrenheit'",
                    required = false) String unit,
            @ToolParam(description = "Open-Meteo language code (e.g. 'en', 'de', 'fr', 'it', 'es', 'pt', 'ru')",
                    required = false) String language) {

        String cityError = InputValidator.validateCity(city);
        if (cityError != null) {
            return ForecastResult.invalidInput(cityError, city);
        }

        String countryError = InputValidator.validateCountryCode(countryCode);
        if (countryError != null) {
            return ForecastResult.invalidInput(countryError, city);
        }

        int resolvedDays = (days == null) ? DEFAULT_FORECAST_DAYS : days;
        if (resolvedDays < MIN_FORECAST_DAYS || resolvedDays > MAX_FORECAST_DAYS) {
            return ForecastResult.invalidInput(
                    "days must be between " + MIN_FORECAST_DAYS + " and " + MAX_FORECAST_DAYS, city);
        }

        String resolvedCountryCode = InputValidator.normaliseCountryCode(countryCode);
        String resolvedUnit = InputValidator.normaliseUnit(unit);
        String resolvedLanguage = InputValidator.normaliseLanguage(language);

        try {
            Optional<GeoResult> match = client.geocode(city, resolvedCountryCode, resolvedLanguage);
            if (match.isEmpty()) {
                return ForecastResult.cityNotFound(city);
            }

            GeoResult geo = match.get();
            if (geo.latitude() == null || geo.longitude() == null) {
                return ForecastResult.cityNotFound(city);
            }

            ForecastUpstream upstream = client.fetchForecast(geo.latitude(), geo.longitude(), resolvedDays, resolvedUnit);

            return toForecastResult(geo, upstream, resolvedUnit);
        } catch (RestClientException e) {
            log.warn("Open-Meteo upstream call failed for city={}", city, e);

            return ForecastResult.upstreamUnavailable();
        }
    }

    @Tool(name = "weather.historical",
            description = """
                    Get historical observed weather for a city on a specific past date via Open-Meteo (archive API).
                    Returns a single daily entry with max/min temperature, precipitation sum, and weather code.
                    'date' must be in ISO format yyyy-MM-dd, strictly in the past, and within the last 80 years.
                    Temperature unit defaults to celsius. Use countryCode to disambiguate common city names.""")
    public HistoricalWeatherResult getHistoricalWeather(
            @ToolParam(description = "The name of a city, e.g. 'Warsaw'") String city,
            @ToolParam(description = "Optional ISO-3166-1 alpha-2 country code to disambiguate the city, e.g. 'PL'",
                    required = false) String countryCode,
            @ToolParam(description = "The date to retrieve, in ISO format yyyy-MM-dd (must be in the past, within 80 years)") String date,
            @ToolParam(description = "Temperature unit: 'celsius' (default) or 'fahrenheit'",
                    required = false) String unit,
            @ToolParam(description = "Open-Meteo language code (e.g. 'en', 'de', 'fr', 'it', 'es', 'pt', 'ru')",
                    required = false) String language) {

        String cityError = InputValidator.validateCity(city);
        if (cityError != null) {
            return HistoricalWeatherResult.invalidInput(cityError, city);
        }

        String countryError = InputValidator.validateCountryCode(countryCode);
        if (countryError != null) {
            return HistoricalWeatherResult.invalidInput(countryError, city);
        }

        String dateError = InputValidator.validateHistoricalDate(date);
        if (dateError != null) {
            return HistoricalWeatherResult.invalidInput(dateError, city);
        }

        String resolvedCountryCode = InputValidator.normaliseCountryCode(countryCode);
        String resolvedUnit = InputValidator.normaliseUnit(unit);
        String resolvedLanguage = InputValidator.normaliseLanguage(language);

        try {
            Optional<GeoResult> match = client.geocode(city, resolvedCountryCode, resolvedLanguage);
            if (match.isEmpty()) {
                return HistoricalWeatherResult.cityNotFound(city);
            }

            GeoResult geo = match.get();
            if (geo.latitude() == null || geo.longitude() == null) {
                return HistoricalWeatherResult.cityNotFound(city);
            }

            ForecastUpstream upstream = client.fetchHistoricalWeather(geo.latitude(), geo.longitude(), date, resolvedUnit);

            return toHistoricalResult(geo, upstream, resolvedUnit);
        } catch (RestClientException e) {
            log.warn("Open-Meteo archive call failed for city={} date={}", city, date, e);

            return HistoricalWeatherResult.upstreamUnavailable();
        }
    }

    @Tool(name = "weather.airQuality",
            description = """
                    Get current air quality data for a city via the Open-Meteo Air Quality API. Returns PM10,
                    PM2.5 (both in µg/m³), US AQI, and European AQI. No temperature unit parameter — air quality
                    metrics have fixed units. Use countryCode to disambiguate common city names.""")
    public AirQualityResult getAirQuality(
            @ToolParam(description = "The name of a city, e.g. 'Warsaw'") String city,
            @ToolParam(description = "Optional ISO-3166-1 alpha-2 country code to disambiguate the city, e.g. 'PL'",
                    required = false) String countryCode,
            @ToolParam(description = "Open-Meteo language code (e.g. 'en', 'de', 'fr', 'it', 'es', 'pt', 'ru')",
                    required = false) String language) {

        String cityError = InputValidator.validateCity(city);
        if (cityError != null) {
            return AirQualityResult.invalidInput(cityError, city);
        }

        String countryError = InputValidator.validateCountryCode(countryCode);
        if (countryError != null) {
            return AirQualityResult.invalidInput(countryError, city);
        }

        String resolvedCountryCode = InputValidator.normaliseCountryCode(countryCode);
        String resolvedLanguage = InputValidator.normaliseLanguage(language);

        try {
            Optional<GeoResult> match = client.geocode(city, resolvedCountryCode, resolvedLanguage);
            if (match.isEmpty()) {
                return AirQualityResult.cityNotFound(city);
            }

            GeoResult geo = match.get();
            if (geo.latitude() == null || geo.longitude() == null) {
                return AirQualityResult.cityNotFound(city);
            }

            AirQualityUpstream upstream = client.fetchAirQuality(geo.latitude(), geo.longitude());

            return toAirQualityResult(geo, upstream);
        } catch (RestClientException e) {
            log.warn("Open-Meteo air quality call failed for city={}", city, e);

            return AirQualityResult.upstreamUnavailable();
        }
    }

    @Tool(name = "weather.geocode",
            description = """
                    Geocode a place name and return up to 'limit' candidate locations via the Open-Meteo Geocoding API.
                    Each candidate contains the resolved name, country, country code, latitude, and longitude.
                    Useful when the LLM needs to disambiguate ambiguous place names (e.g. 'Paris' → list of matches to
                    show the user). 'limit' defaults to 5, range 1–10.""")
    public GeocodeResult geocode(
            @ToolParam(description = "The place name to geocode, e.g. 'Paris'") String query,
            @ToolParam(description = "Maximum number of candidates to return, 1–10 (default 5)",
                    required = false) Integer limit,
            @ToolParam(description = "Open-Meteo language code (e.g. 'en', 'de', 'fr', 'it', 'es', 'pt', 'ru')",
                    required = false) String language) {

        String queryError = InputValidator.validatePlaceName(query, "Query");
        if (queryError != null) {
            return GeocodeResult.invalidInput(queryError, query);
        }

        int resolvedLimit = (limit == null) ? DEFAULT_GEOCODE_LIMIT : limit;
        if (resolvedLimit < MIN_GEOCODE_LIMIT || resolvedLimit > MAX_GEOCODE_LIMIT) {
            return GeocodeResult.invalidInput(
                    "limit must be between " + MIN_GEOCODE_LIMIT + " and " + MAX_GEOCODE_LIMIT, query);
        }

        String resolvedLanguage = InputValidator.normaliseLanguage(language);

        try {
            List<GeoResult> results = client.geocodeAll(query, resolvedLimit, resolvedLanguage);
            if (results.isEmpty()) {
                return GeocodeResult.noResults(query);
            }

            List<ResolvedLocation> candidates = results.stream()
                    .map(ResolvedLocation::from)
                    .toList();

            return GeocodeResult.ok(candidates);
        } catch (RestClientException e) {
            log.warn("Open-Meteo geocoding call failed for query={}", query, e);

            return GeocodeResult.upstreamUnavailable();
        }
    }

    private static CurrentWeatherResult toResult(GeoResult geo, CurrentWeatherUpstream upstream, String unit) {
        if (upstream == null || upstream.currentWeather() == null) {
            return CurrentWeatherResult.upstreamUnavailable();
        }

        CurrentWeatherUpstream.Current current = upstream.currentWeather();
        ResolvedLocation location = ResolvedLocation.from(geo);
        Temperature temperature = new Temperature(current.temperature(), unit);
        Wind wind = new Wind(current.windSpeed(), current.windDirection(), WIND_UNIT);

        return CurrentWeatherResult.ok(location, temperature, current.weatherCode(), wind, current.time());
    }

    private static ForecastResult toForecastResult(GeoResult geo, ForecastUpstream upstream, String unit) {
        if (upstream == null || upstream.daily() == null) {
            return ForecastResult.upstreamUnavailable();
        }

        ForecastUpstream.Daily daily = upstream.daily();
        ResolvedLocation location = ResolvedLocation.from(geo);

        List<String> times = daily.time();
        if (times == null || times.isEmpty()) {
            return ForecastResult.upstreamUnavailable();
        }

        List<DailyForecast> forecasts = IntStream.range(0, times.size())
                .mapToObj(i -> new DailyForecast(
                        times.get(i),
                        getOrNull(daily.temperature2mMax(), i),
                        getOrNull(daily.temperature2mMin(), i),
                        getOrNull(daily.precipitationSum(), i),
                        getIntOrNull(daily.weatherCode(), i)
                ))
                .toList();

        return ForecastResult.ok(location, forecasts, unit);
    }

    private static HistoricalWeatherResult toHistoricalResult(GeoResult geo, ForecastUpstream upstream, String unit) {
        if (upstream == null || upstream.daily() == null) {
            return HistoricalWeatherResult.upstreamUnavailable();
        }

        ForecastUpstream.Daily daily = upstream.daily();
        ResolvedLocation location = ResolvedLocation.from(geo);

        List<String> times = daily.time();
        if (times == null || times.isEmpty()) {
            return HistoricalWeatherResult.upstreamUnavailable();
        }

        DailyForecast day = new DailyForecast(
                times.getFirst(),
                getOrNull(daily.temperature2mMax(), 0),
                getOrNull(daily.temperature2mMin(), 0),
                getOrNull(daily.precipitationSum(), 0),
                getIntOrNull(daily.weatherCode(), 0)
        );

        return HistoricalWeatherResult.ok(location, day, unit);
    }

    private static AirQualityResult toAirQualityResult(GeoResult geo, AirQualityUpstream upstream) {
        if (upstream == null || upstream.current() == null) {
            return AirQualityResult.upstreamUnavailable();
        }

        AirQualityUpstream.Current current = upstream.current();
        ResolvedLocation location = ResolvedLocation.from(geo);

        return AirQualityResult.ok(location, current.pm10(), current.pm25(), current.usAqi(), current.europeanAqi());
    }

    private static Double getOrNull(List<Double> list, int index) {
        if (list == null || index >= list.size()) {
            return null;
        }

        return list.get(index);
    }

    private static Integer getIntOrNull(List<Integer> list, int index) {
        if (list == null || index >= list.size()) {
            return null;
        }

        return list.get(index);
    }
}
