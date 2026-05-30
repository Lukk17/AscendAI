package com.lukk.ascend.ai.mcp.weather.service;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

import java.text.Normalizer;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class InputValidator {

    public static final int CITY_MAX_LENGTH = 100;
    public static final String DEFAULT_LANGUAGE = "en";
    public static final String DEFAULT_UNIT = "celsius";
    public static final int MAX_HISTORICAL_YEARS = 80;

    public static final Set<String> SUPPORTED_LANGUAGES = Set.of("en", "de", "fr", "it", "es", "pt", "ru");
    public static final Set<String> SUPPORTED_UNITS = Set.of("celsius", "fahrenheit");
    public static final Set<String> SUPPORTED_COUNTRY_CODES = Arrays.stream(Locale.getISOCountries())
            .collect(Collectors.toUnmodifiableSet());

    private static final Pattern PLACE_PATTERN = Pattern.compile("[\\p{L}\\p{M}][\\p{L}\\p{M}\\p{Zs},.'\\-]*");
    private static final Pattern COUNTRY_CODE_PATTERN = Pattern.compile("[A-Za-z]{2}");

    public static String validateCity(String city) {
        return validatePlaceName(city, "City");
    }

    public static String validatePlaceName(String input, String fieldLabel) {
        if (input == null || input.isBlank()) {
            return fieldLabel + " must not be blank";
        }
        if (input.length() > CITY_MAX_LENGTH) {
            return fieldLabel + " must be at most " + CITY_MAX_LENGTH + " characters";
        }
        String normalised = Normalizer.normalize(input, Normalizer.Form.NFKC);
        if (!PLACE_PATTERN.matcher(normalised).matches()) {
            return fieldLabel + " contains unsupported characters";
        }

        return null;
    }

    public static String validateCountryCode(String countryCode) {
        if (countryCode == null || countryCode.isBlank()) {
            return null;
        }
        if (!COUNTRY_CODE_PATTERN.matcher(countryCode).matches()) {
            return "Country code must be ISO-3166-1 alpha-2 (two letters)";
        }
        if (!SUPPORTED_COUNTRY_CODES.contains(countryCode.toUpperCase())) {
            return "Country code is not a known ISO-3166-1 alpha-2 code";
        }

        return null;
    }

    public static String validateHistoricalDate(String date) {
        if (date == null || date.isBlank()) {
            return "date must not be blank";
        }
        LocalDate parsed;
        try {
            parsed = LocalDate.parse(date);
        } catch (DateTimeParseException e) {
            return "date must be in ISO format yyyy-MM-dd";
        }
        LocalDate today = LocalDate.now();
        if (!parsed.isBefore(today)) {
            return "date must be strictly in the past";
        }
        if (parsed.isBefore(today.minusYears(MAX_HISTORICAL_YEARS))) {
            return "date must be within the last " + MAX_HISTORICAL_YEARS + " years";
        }

        return null;
    }

    public static String normaliseUnit(String unit) {
        if (unit == null || unit.isBlank()) {
            return DEFAULT_UNIT;
        }
        String lower = unit.toLowerCase();

        return SUPPORTED_UNITS.contains(lower) ? lower : DEFAULT_UNIT;
    }

    public static String normaliseLanguage(String language) {
        if (language == null || language.isBlank()) {
            return DEFAULT_LANGUAGE;
        }
        String lower = language.toLowerCase();

        return SUPPORTED_LANGUAGES.contains(lower) ? lower : DEFAULT_LANGUAGE;
    }

    public static String normaliseCountryCode(String countryCode) {
        if (countryCode == null || countryCode.isBlank()) {
            return null;
        }

        return countryCode.toUpperCase();
    }

    public static String normaliseCacheKey(String value) {
        if (value == null) {
            return null;
        }
        String normalised = Normalizer.normalize(value, Normalizer.Form.NFKC);

        return normalised.toLowerCase().trim();
    }
}
