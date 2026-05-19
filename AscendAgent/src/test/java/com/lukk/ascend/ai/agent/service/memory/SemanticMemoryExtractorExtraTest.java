package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Direct exercise of {@code findLastBalancedJsonArray} (via the public {@code extractFactsFromJson}
 * facade) covering the deeply-nested, escaped-quote, only-{@code [}, only-{@code ]}, blank-input and
 * "balanced-but-invalid JSON" branches.
 */
class SemanticMemoryExtractorExtraTest {

    private final SemanticMemoryExtractor extractor = new SemanticMemoryExtractor(
            null, null, null, new ObjectMapper(), null, null);

    @Test
    void extractFactsFromJson_WhenNullOrBlank_ThenReturnsEmpty() {
        assertThat(extractor.extractFactsFromJson(null)).isEmpty();
        assertThat(extractor.extractFactsFromJson("")).isEmpty();
        assertThat(extractor.extractFactsFromJson("   \n\t")).isEmpty();
    }

    @Test
    void extractFactsFromJson_WhenOnlyOpenBracket_ThenReturnsEmpty() {
        assertThat(extractor.extractFactsFromJson("Thinking... [")).isEmpty();
    }

    @Test
    void extractFactsFromJson_WhenOnlyCloseBracket_ThenReturnsEmpty() {
        assertThat(extractor.extractFactsFromJson("Thinking... ]")).isEmpty();
    }

    @Test
    void extractFactsFromJson_WhenDeeplyNestedArrays_ThenSelectsLastBalanced() {
        String input = "intro [\"a\"] more thinking [[\"nested\"], [\"x\", \"y\"]]";

        List<String> result = extractor.extractFactsFromJson(input);

        // The last balanced array is the outer `[[\"nested\"], [\"x\", \"y\"]]`,
        // which doesn't deserialize as List<String> (it's nested arrays).
        // The fallback then logs a warn and returns empty.
        assertThat(result).isEmpty();
    }

    @Test
    void extractFactsFromJson_WhenBracketsInsideStrings_ThenIgnoresThem() {
        // The "[" inside the string literal must NOT trip the depth counter.
        String input = "Reasoning: \"the array starts with [\" -- final: [\"User likes [brackets]\"]";

        List<String> result = extractor.extractFactsFromJson(input);

        assertThat(result).containsExactly("User likes [brackets]");
    }

    @Test
    void extractFactsFromJson_WhenEscapedQuotes_ThenStillExtracts() {
        // Escaped quote inside a string should keep us in-string and not flip inString flag.
        String input = "Some prose [\"User said \\\"hello\\\" loudly\"]";

        List<String> result = extractor.extractFactsFromJson(input);

        assertThat(result).containsExactly("User said \"hello\" loudly");
    }

    @Test
    void extractFactsFromJson_WhenBalancedButInvalidJsonInside_ThenReturnsEmpty() {
        // Balanced brackets but malformed JSON content → embedded parse fails too.
        String input = "Final: [not valid json content]";

        List<String> result = extractor.extractFactsFromJson(input);

        assertThat(result).isEmpty();
    }

    @Test
    void extractFactsFromJson_WhenMarkdownFenceWithJson_ThenStripsFences() {
        String input = "```json\n[\"fact-A\", \"fact-B\"]\n```";

        List<String> result = extractor.extractFactsFromJson(input);

        assertThat(result).containsExactly("fact-A", "fact-B");
    }

    @Test
    void extractFactsFromJson_WhenTrailingMarkdownFenceOnly_ThenStripsTrailing() {
        String input = "[\"only-fact\"]\n```";

        List<String> result = extractor.extractFactsFromJson(input);

        assertThat(result).containsExactly("only-fact");
    }
}
