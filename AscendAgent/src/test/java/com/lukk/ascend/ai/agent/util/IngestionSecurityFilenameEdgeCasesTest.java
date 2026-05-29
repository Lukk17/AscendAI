package com.lukk.ascend.ai.agent.util;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class IngestionSecurityFilenameEdgeCasesTest {

    @DisplayName("sanitize filename returns hard cut without preserving ext when extension longer than max length")
    @Test
    void sanitizeFilename_WhenExtensionLongerThanMaxLength_ThenReturnsHardCutWithoutPreservingExt() {
        // given — extension longer than 200 -> truncatePreservingExtension hits the `ext.length() >= MAX_LENGTH` branch
        String longExt = "x".repeat(250);
        String input = "a." + longExt;

        // when
        String result = IngestionSecurity.sanitizeFilename(input);

        // then — hard-cut from the start; the dot may be preserved but extension is severed
        assertThat(result).hasSize(200);
        assertThat(result).startsWith("a.");
    }

    @DisplayName("sanitize filename truncated hard cut when no dot")
    @Test
    void sanitizeFilename_WhenNoDot_ThenTruncatedHardCut() {
        // given — dotIdx <= 0 -> returns name.substring(0, MAX_LENGTH) without preserving extension
        String noExt = "n".repeat(300);

        // when
        String result = IngestionSecurity.sanitizeFilename(noExt);

        // then
        assertThat(result).hasSize(200);
        assertThat(result).doesNotContain(".");
    }

    @DisplayName("sanitize filename truncated hard cut when trailing dot")
    @Test
    void sanitizeFilename_WhenTrailingDot_ThenTruncatedHardCut() {
        // given — dotIdx >= name.length() - 1 -> trailing dot path falls into hard-cut branch
        String trailingDot = "n".repeat(299) + ".";

        // when
        String result = IngestionSecurity.sanitizeFilename(trailingDot);

        // then
        assertThat(result).hasSize(200);
    }

    @DisplayName("sanitize filename stripped when windows backslash traversal")
    @Test
    void sanitizeFilename_WhenWindowsBackslashTraversal_ThenStripped() {
        // when
        String result = IngestionSecurity.sanitizeFilename("..\\..\\system32\\hosts");

        // then
        assertThat(result).doesNotContain("\\");
        assertThat(result).doesNotContain("/");
        assertThat(result).doesNotStartWith(".");
    }

    @DisplayName("sanitize filename collapsed to single when multiple dots in a row")
    @Test
    void sanitizeFilename_WhenMultipleDotsInARow_ThenCollapsedToSingle() {
        // when
        String result = IngestionSecurity.sanitizeFilename("file...ext");

        // then
        assertThat(result).doesNotContain("..");
        assertThat(result).contains(".");
    }
}
