package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionSecurityExtraTest {

    @Test
    void sanitizeFilename_WhenExtensionLongerThanMaxLength_ThenReturnsHardCutWithoutPreservingExt() {
        // Extension longer than 200 → truncatePreservingExtension hits the `ext.length() >= MAX_LENGTH` branch.
        String longExt = "x".repeat(250);
        String input = "a." + longExt;

        String result = IngestionSecurity.sanitizeFilename(input);

        assertThat(result).hasSize(200);
        // Hard-cut from the start; the dot may be preserved but extension is severed.
        assertThat(result).startsWith("a.");
    }

    @Test
    void sanitizeFilename_WhenNoDot_ThenTruncatedHardCut() {
        // dotIdx <= 0 → returns name.substring(0, MAX_LENGTH) without preserving extension.
        String noExt = "n".repeat(300);

        String result = IngestionSecurity.sanitizeFilename(noExt);

        assertThat(result).hasSize(200);
        assertThat(result).doesNotContain(".");
    }

    @Test
    void sanitizeFilename_WhenTrailingDot_ThenTruncatedHardCut() {
        // dotIdx >= name.length() - 1 → trailing dot path falls into hard-cut branch.
        // Build a 300-char base ending in '.' so after sanitization the dot survives at end.
        String trailingDot = "n".repeat(299) + ".";

        String result = IngestionSecurity.sanitizeFilename(trailingDot);

        assertThat(result).hasSize(200);
    }

    @Test
    void sanitizeFilename_WhenWindowsBackslashTraversal_ThenStripped() {
        String result = IngestionSecurity.sanitizeFilename("..\\..\\system32\\hosts");

        assertThat(result).doesNotContain("\\");
        assertThat(result).doesNotContain("/");
        assertThat(result).doesNotStartWith(".");
    }

    @Test
    void sanitizeFilename_WhenMultipleDotsInARow_ThenCollapsedToSingle() {
        String result = IngestionSecurity.sanitizeFilename("file...ext");

        assertThat(result).doesNotContain("..");
        assertThat(result).contains(".");
    }
}
