package com.lukk.ascend.ai.mcp.weather.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;

class InputValidatorTest {

    @Test
    @DisplayName("validateCity returns null for a valid city name")
    void validateCity_validName_returnsNull() {
        assertThat(InputValidator.validateCity("Warsaw")).isNull();
    }

    @Test
    @DisplayName("validateCity returns error when city is null")
    void validateCity_null_returnsBlankError() {
        assertThat(InputValidator.validateCity(null)).containsIgnoringCase("blank");
    }

    @Test
    @DisplayName("validateCity returns error when city is blank")
    void validateCity_blank_returnsBlankError() {
        assertThat(InputValidator.validateCity("   ")).containsIgnoringCase("blank");
    }

    @Test
    @DisplayName("validateCity returns error when city exceeds max length")
    void validateCity_tooLong_returnsLengthError() {
        String longCity = "A".repeat(InputValidator.CITY_MAX_LENGTH + 1);
        assertThat(InputValidator.validateCity(longCity)).containsIgnoringCase("characters");
    }

    @Test
    @DisplayName("validateCity returns error when city contains unsupported characters")
    void validateCity_controlCharacters_returnsUnsupportedCharactersError() {
        assertThat(InputValidator.validateCity("Warsaw\r\n")).containsIgnoringCase("unsupported");
    }

    @Test
    @DisplayName("validatePlaceName uses the supplied label in the error message")
    void validatePlaceName_blankInput_errorMessageContainsLabel() {
        String error = InputValidator.validatePlaceName("   ", "Query");
        assertThat(error).startsWith("Query");
    }

    @Test
    @DisplayName("validatePlaceName with label City delegates same logic as validateCity")
    void validatePlaceName_cityLabel_sameResultAsValidateCity() {
        String viaPlaceName = InputValidator.validatePlaceName("Warsaw", "City");
        String viaValidateCity = InputValidator.validateCity("Warsaw");
        assertThat(viaPlaceName).isEqualTo(viaValidateCity);
    }

    @Test
    @DisplayName("validatePlaceName applies NFKC normalisation so compatibility characters are accepted")
    void validatePlaceName_nfkcCompatibilityChar_normalises() {
        // U+FF37 FULLWIDTH LATIN CAPITAL LETTER W normalises to 'W' under NFKC
        String fullwidthW = "Ｗarsaw";
        assertThat(InputValidator.validatePlaceName(fullwidthW, "City")).isNull();
    }

    @Test
    @DisplayName("validateCountryCode returns null for a valid two-letter ISO country code")
    void validateCountryCode_validCode_returnsNull() {
        assertThat(InputValidator.validateCountryCode("US")).isNull();
        assertThat(InputValidator.validateCountryCode("PL")).isNull();
        assertThat(InputValidator.validateCountryCode("DE")).isNull();
    }

    @Test
    @DisplayName("validateCountryCode returns null when country code is null")
    void validateCountryCode_null_returnsNull() {
        assertThat(InputValidator.validateCountryCode(null)).isNull();
    }

    @Test
    @DisplayName("validateCountryCode returns null when country code is blank")
    void validateCountryCode_blank_returnsNull() {
        assertThat(InputValidator.validateCountryCode("   ")).isNull();
    }

    @Test
    @DisplayName("validateCountryCode returns error when country code is not two letters")
    void validateCountryCode_threeLetters_returnsFormatError() {
        assertThat(InputValidator.validateCountryCode("POL")).containsIgnoringCase("alpha-2");
    }

    @Test
    @DisplayName("validateCountryCode returns error when country code is ZZ (two letters but not a real ISO code)")
    void validateCountryCode_zzCode_returnsUnknownIsoError() {
        assertThat(InputValidator.validateCountryCode("ZZ")).containsIgnoringCase("ISO-3166-1");
    }

    @Test
    @DisplayName("validateCountryCode returns error when country code is AA (two letters but not a real ISO code)")
    void validateCountryCode_aaCode_returnsUnknownIsoError() {
        assertThat(InputValidator.validateCountryCode("AA")).containsIgnoringCase("ISO-3166-1");
    }

    @Test
    @DisplayName("validateCountryCode accepts lowercase input by uppercasing internally")
    void validateCountryCode_lowercase_returnsNull() {
        assertThat(InputValidator.validateCountryCode("us")).isNull();
    }

    @Test
    @DisplayName("validateHistoricalDate returns null for a valid past date")
    void validateHistoricalDate_validPastDate_returnsNull() {
        assertThat(InputValidator.validateHistoricalDate("2020-01-15")).isNull();
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date is null")
    void validateHistoricalDate_null_returnsBlankError() {
        assertThat(InputValidator.validateHistoricalDate(null)).containsIgnoringCase("blank");
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date is blank")
    void validateHistoricalDate_blank_returnsBlankError() {
        assertThat(InputValidator.validateHistoricalDate("   ")).containsIgnoringCase("blank");
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date format is wrong")
    void validateHistoricalDate_wrongFormat_returnsFormatError() {
        assertThat(InputValidator.validateHistoricalDate("30-01-2020")).containsIgnoringCase("format");
    }

    @Test
    @DisplayName("validateHistoricalDate error does not echo the bad date value in the message")
    void validateHistoricalDate_wrongFormat_errorDoesNotEchoInput() {
        String error = InputValidator.validateHistoricalDate("not-a-date");
        assertThat(error).doesNotContain("not-a-date");
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date is today")
    void validateHistoricalDate_today_returnsPastError() {
        assertThat(InputValidator.validateHistoricalDate(LocalDate.now().toString()))
                .containsIgnoringCase("past");
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date is in the future")
    void validateHistoricalDate_future_returnsPastError() {
        assertThat(InputValidator.validateHistoricalDate(LocalDate.now().plusDays(1).toString()))
                .containsIgnoringCase("past");
    }

    @Test
    @DisplayName("validateHistoricalDate returns error when date is older than 80 years")
    void validateHistoricalDate_tooOld_returnsYearsError() {
        String ancient = LocalDate.now().minusYears(InputValidator.MAX_HISTORICAL_YEARS + 1).toString();
        assertThat(InputValidator.validateHistoricalDate(ancient))
                .containsIgnoringCase("80 years");
    }

    @Test
    @DisplayName("normaliseUnit returns the recognised unit unchanged")
    void normaliseUnit_celsius_returnsCelsius() {
        assertThat(InputValidator.normaliseUnit("celsius")).isEqualTo("celsius");
    }

    @Test
    @DisplayName("normaliseUnit defaults to celsius for an unrecognised value")
    void normaliseUnit_unknown_defaultsToCelsius() {
        assertThat(InputValidator.normaliseUnit("kelvin")).isEqualTo(InputValidator.DEFAULT_UNIT);
    }

    @Test
    @DisplayName("normaliseUnit defaults to celsius when null")
    void normaliseUnit_null_defaultsToCelsius() {
        assertThat(InputValidator.normaliseUnit(null)).isEqualTo(InputValidator.DEFAULT_UNIT);
    }

    @Test
    @DisplayName("normaliseLanguage returns the recognised language unchanged")
    void normaliseLanguage_en_returnsEn() {
        assertThat(InputValidator.normaliseLanguage("en")).isEqualTo("en");
    }

    @Test
    @DisplayName("normaliseLanguage defaults to en for an unrecognised language")
    void normaliseLanguage_unknown_defaultsToEn() {
        assertThat(InputValidator.normaliseLanguage("zz")).isEqualTo(InputValidator.DEFAULT_LANGUAGE);
    }

    @Test
    @DisplayName("normaliseCountryCode returns null when input is blank")
    void normaliseCountryCode_blank_returnsNull() {
        assertThat(InputValidator.normaliseCountryCode("   ")).isNull();
    }

    @Test
    @DisplayName("normaliseCountryCode returns null when input is null")
    void normaliseCountryCode_null_returnsNull() {
        assertThat(InputValidator.normaliseCountryCode(null)).isNull();
    }

    @Test
    @DisplayName("normaliseCountryCode uppercases the input")
    void normaliseCountryCode_lowercase_returnsUppercase() {
        assertThat(InputValidator.normaliseCountryCode("pl")).isEqualTo("PL");
    }

    @Test
    @DisplayName("normaliseCacheKey returns null when input is null")
    void normaliseCacheKey_null_returnsNull() {
        assertThat(InputValidator.normaliseCacheKey(null)).isNull();
    }

    @Test
    @DisplayName("normaliseCacheKey lowercases and trims the input")
    void normaliseCacheKey_mixedCase_returnsLowercaseTrimmed() {
        assertThat(InputValidator.normaliseCacheKey("  Warsaw  ")).isEqualTo("warsaw");
    }

    @Test
    @DisplayName("normaliseCacheKey applies NFKC normalisation so compatibility characters become ASCII")
    void normaliseCacheKey_fullwidthLetters_normalisesToAscii() {
        // U+FF37 FULLWIDTH LATIN CAPITAL LETTER W normalises to 'W' → 'w' after lowercasing
        assertThat(InputValidator.normaliseCacheKey("Ｗarsaw")).isEqualTo("warsaw");
    }
}
