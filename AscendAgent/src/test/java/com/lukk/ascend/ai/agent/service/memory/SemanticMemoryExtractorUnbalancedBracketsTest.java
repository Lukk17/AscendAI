package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SemanticMemoryExtractorUnbalancedBracketsTest {

    private final SemanticMemoryExtractor extractor = new SemanticMemoryExtractor(
            null, null, null, new ObjectMapper(), null, null);

    @Test
    @DisplayName("extractFactsFromJson returns empty for null, empty, or blank input")
    void extractFactsFromJson_WhenNullOrBlank_ThenReturnsEmpty() {
        // then
        assertThat(extractor.extractFactsFromJson(null)).isEmpty();
        assertThat(extractor.extractFactsFromJson("")).isEmpty();
        assertThat(extractor.extractFactsFromJson("   \n\t")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty when input has only an opening bracket")
    void extractFactsFromJson_WhenOnlyOpenBracket_ThenReturnsEmpty() {
        // then
        assertThat(extractor.extractFactsFromJson("Thinking... [")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty when input has only a closing bracket")
    void extractFactsFromJson_WhenOnlyCloseBracket_ThenReturnsEmpty() {
        // then
        assertThat(extractor.extractFactsFromJson("Thinking... ]")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty for deeply nested arrays that cannot be deserialized as List<String>")
    void extractFactsFromJson_WhenDeeplyNestedArrays_ThenSelectsLastBalanced() {
        // given
        String input = "intro [\"a\"] more thinking [[\"nested\"], [\"x\", \"y\"]]";

        // when
        List<String> result = extractor.extractFactsFromJson(input);

        // then — last balanced array is the outer nested one; does not deserialize as List<String>
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson ignores bracket characters inside string literals")
    void extractFactsFromJson_WhenBracketsInsideStrings_ThenIgnoresThem() {
        // given — the "[" inside the string literal must NOT trip the depth counter
        String input = "Reasoning: \"the array starts with [\" -- final: [\"User likes [brackets]\"]";

        // then
        assertThat(extractor.extractFactsFromJson(input)).containsExactly("User likes [brackets]");
    }

    @Test
    @DisplayName("extractFactsFromJson correctly handles escaped quotes inside string values")
    void extractFactsFromJson_WhenEscapedQuotes_ThenStillExtracts() {
        // given — escaped quote inside a string should keep us in-string and not flip inString flag
        String input = "Some prose [\"User said \\\"hello\\\" loudly\"]";

        // then
        assertThat(extractor.extractFactsFromJson(input)).containsExactly("User said \"hello\" loudly");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty for balanced brackets that contain non-JSON content")
    void extractFactsFromJson_WhenBalancedButInvalidJsonInside_ThenReturnsEmpty() {
        // given — balanced brackets but malformed JSON content -> embedded parse fails too
        String input = "Final: [not valid json content]";

        // then
        assertThat(extractor.extractFactsFromJson(input)).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson strips markdown code fences and extracts the JSON array")
    void extractFactsFromJson_WhenMarkdownFenceWithJson_ThenStripsFences() {
        // given
        String input = "```json\n[\"fact-A\", \"fact-B\"]\n```";

        // then
        assertThat(extractor.extractFactsFromJson(input)).containsExactly("fact-A", "fact-B");
    }

    @Test
    @DisplayName("extractFactsFromJson strips trailing markdown fence and extracts facts")
    void extractFactsFromJson_WhenTrailingMarkdownFenceOnly_ThenStripsTrailing() {
        // given
        String input = "[\"only-fact\"]\n```";

        // then
        assertThat(extractor.extractFactsFromJson(input)).containsExactly("only-fact");
    }
}
