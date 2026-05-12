package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionSecurityTest {

    @Test
    void sanitizeFilename_WhenNull_ThenReturnsFallback() {
        assertThat(IngestionSecurity.sanitizeFilename(null)).isEqualTo("unknown_file");
    }

    @Test
    void sanitizeFilename_WhenEmpty_ThenReturnsFallback() {
        assertThat(IngestionSecurity.sanitizeFilename("")).isEqualTo("unknown_file");
    }

    @Test
    void sanitizeFilename_WhenNormalName_ThenUnchanged() {
        assertThat(IngestionSecurity.sanitizeFilename("notes.md")).isEqualTo("notes.md");
    }

    @Test
    void sanitizeFilename_WhenPathTraversal_ThenNoSlashesNoLeadingDots() {
        String result = IngestionSecurity.sanitizeFilename("../../etc/passwd");

        assertThat(result).doesNotContain("/");
        assertThat(result).doesNotStartWith(".");
    }

    @Test
    void sanitizeFilename_WhenControlChars_ThenStripped() {
        char bel = (char) 0x07;
        char nul = (char) 0x00;
        char esc = (char) 0x1B;
        char del = (char) 0x7F;
        String input = "fil" + bel + "en" + nul + "am" + esc + "e" + del + ".txt";

        String result = IngestionSecurity.sanitizeFilename(input);

        assertThat(result).doesNotContain(String.valueOf(bel));
        assertThat(result).doesNotContain(String.valueOf(nul));
        assertThat(result).doesNotContain(String.valueOf(esc));
        assertThat(result).doesNotContain(String.valueOf(del));
        assertThat(result).isEqualTo("filename.txt");
    }

    @Test
    void sanitizeFilename_WhenOnlySpecialChars_ThenReturnsFallbackOrUnderscore() {
        String result = IngestionSecurity.sanitizeFilename("!@#$%^&*");

        assertThat(result).isIn("unknown_file", "_");
    }

    @Test
    void sanitizeFilename_WhenSuperLong_ThenTruncatedPreservingExtension() {
        String longBase = "a".repeat(300);
        String input = longBase + ".pdf";

        String result = IngestionSecurity.sanitizeFilename(input);

        assertThat(result).hasSizeLessThanOrEqualTo(200);
        assertThat(result).endsWith(".pdf");
    }

    @Test
    void sanitizeFilename_WhenLeadingDots_ThenStripped() {
        assertThat(IngestionSecurity.sanitizeFilename("...secret.txt"))
                .doesNotStartWith(".")
                .isEqualTo("secret.txt");
    }

    @Test
    void sanitizeFilename_WhenMultipleConsecutiveUnderscores_ThenCollapsed() {
        String result = IngestionSecurity.sanitizeFilename("a   b!!!c.txt");

        assertThat(result).doesNotContain("__");
        assertThat(result).isEqualTo("a_b_c.txt");
    }
}
