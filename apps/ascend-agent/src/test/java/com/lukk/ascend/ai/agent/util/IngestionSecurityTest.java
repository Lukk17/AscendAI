package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionSecurityTest {

    @DisplayName("sanitize filename returns fallback when null")
    @Test
    void sanitizeFilename_WhenNull_ThenReturnsFallback() {
        // then
        assertThat(IngestionSecurity.sanitizeFilename(null)).isEqualTo("unknown_file");
    }

    @DisplayName("sanitize filename returns fallback when empty")
    @Test
    void sanitizeFilename_WhenEmpty_ThenReturnsFallback() {
        // then
        assertThat(IngestionSecurity.sanitizeFilename("")).isEqualTo("unknown_file");
    }

    @DisplayName("sanitize filename unchanged when normal name")
    @Test
    void sanitizeFilename_WhenNormalName_ThenUnchanged() {
        // then
        assertThat(IngestionSecurity.sanitizeFilename("notes.md")).isEqualTo("notes.md");
    }

    @DisplayName("sanitize filename no slashes no leading dots when path traversal")
    @Test
    void sanitizeFilename_WhenPathTraversal_ThenNoSlashesNoLeadingDots() {
        // when
        String result = IngestionSecurity.sanitizeFilename("../../etc/passwd");

        // then
        assertThat(result).doesNotContain("/");
        assertThat(result).doesNotStartWith(".");
    }

    @DisplayName("sanitize filename stripped when control chars")
    @Test
    void sanitizeFilename_WhenControlChars_ThenStripped() {
        // given
        char bel = (char) 0x07;
        char nul = (char) 0x00;
        char esc = (char) 0x1B;
        char del = (char) 0x7F;
        String input = "fil" + bel + "en" + nul + "am" + esc + "e" + del + ".txt";

        // when
        String result = IngestionSecurity.sanitizeFilename(input);

        // then
        assertThat(result).doesNotContain(String.valueOf(bel));
        assertThat(result).doesNotContain(String.valueOf(nul));
        assertThat(result).doesNotContain(String.valueOf(esc));
        assertThat(result).doesNotContain(String.valueOf(del));
        assertThat(result).isEqualTo("filename.txt");
    }

    @DisplayName("sanitize filename returns fallback or underscore when only special chars")
    @Test
    void sanitizeFilename_WhenOnlySpecialChars_ThenReturnsFallbackOrUnderscore() {
        // when
        String result = IngestionSecurity.sanitizeFilename("!@#$%^&*");

        // then
        assertThat(result).isIn("unknown_file", "_");
    }

    @DisplayName("sanitize filename truncated preserving extension when super long")
    @Test
    void sanitizeFilename_WhenSuperLong_ThenTruncatedPreservingExtension() {
        // given
        String longBase = "a".repeat(300);
        String input = longBase + ".pdf";

        // when
        String result = IngestionSecurity.sanitizeFilename(input);

        // then
        assertThat(result).hasSizeLessThanOrEqualTo(200);
        assertThat(result).endsWith(".pdf");
    }

    @DisplayName("sanitize filename stripped when leading dots")
    @Test
    void sanitizeFilename_WhenLeadingDots_ThenStripped() {
        // then
        assertThat(IngestionSecurity.sanitizeFilename("...secret.txt"))
                .doesNotStartWith(".")
                .isEqualTo("secret.txt");
    }

    @DisplayName("sanitize filename collapsed when multiple consecutive underscores")
    @Test
    void sanitizeFilename_WhenMultipleConsecutiveUnderscores_ThenCollapsed() {
        // when
        String result = IngestionSecurity.sanitizeFilename("a   b!!!c.txt");

        // then
        assertThat(result).doesNotContain("__");
        assertThat(result).isEqualTo("a_b_c.txt");
    }
}
