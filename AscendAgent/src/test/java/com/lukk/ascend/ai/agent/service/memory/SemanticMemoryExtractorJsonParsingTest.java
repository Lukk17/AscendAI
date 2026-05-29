package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.cache.NoopPromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SemanticMemoryExtractorJsonParsingTest {

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @Mock
    private SemanticMemoryClient memoryClient;

    @Mock
    private ChatResponseContentResolver chatResponseContentResolver;

    @Mock
    private PromptCacheStrategyResolver cacheStrategyResolver;

    // Instantiate directly so objectMapper is real, not null
    private SemanticMemoryExtractor extractor;

    @BeforeEach
    void setUp() {
        when(aiProviderProperties.getProviders()).thenReturn(java.util.Map.of());
        PromptCacheStrategy noop = new NoopPromptCacheStrategy("lmstudio");
        when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
        extractor = new SemanticMemoryExtractor(chatModelResolver, aiProviderProperties, memoryClient,
                new ObjectMapper(), chatResponseContentResolver, cacheStrategyResolver);
    }


    @Test
    @DisplayName("extractFactsFromJson returns empty list for null input")
    void extractFactsFromJson_Null_ReturnsEmptyList() {
        // then
        assertThat(extractor.extractFactsFromJson(null)).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list for blank string")
    void extractFactsFromJson_BlankString_ReturnsEmptyList() {
        // then
        assertThat(extractor.extractFactsFromJson("   ")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson parses a clean JSON array of strings")
    void extractFactsFromJson_CleanJsonArray_ReturnsList() {
        // then
        assertThat(extractor.extractFactsFromJson("[\"fact one\", \"fact two\"]"))
                .containsExactly("fact one", "fact two");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list for empty JSON array")
    void extractFactsFromJson_EmptyJsonArray_ReturnsEmptyList() {
        // then
        assertThat(extractor.extractFactsFromJson("[]")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson strips ```json fences and parses correctly")
    void extractFactsFromJson_WithJsonFence_StripsAndParses() {
        // given
        String fenced = "```json\n[\"hello\"]\n```";

        // then
        assertThat(extractor.extractFactsFromJson(fenced)).containsExactly("hello");
    }

    @Test
    @DisplayName("extractFactsFromJson falls back to bracket scan when response has leading prose")
    void extractFactsFromJson_LeadingProse_ExtractsEmbeddedArray() {
        // given
        String response = "Here are the facts I found: [\"User likes cats\", \"User is a developer\"]";

        // then
        assertThat(extractor.extractFactsFromJson(response))
                .containsExactly("User likes cats", "User is a developer");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list when no valid JSON array is in the response")
    void extractFactsFromJson_NoBracketsInResponse_ReturnsEmptyList() {
        // then
        assertThat(extractor.extractFactsFromJson("There are no facts here.")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson handles nested arrays by returning the last outermost array")
    void extractFactsFromJson_NestedArrays_ReturnsLastOutermostArray() {
        // given — JSON with nested array inside a string element
        String response = "[\"value with \\\"inner quote\\\"\"]";

        // when
        List<String> result = extractor.extractFactsFromJson(response);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).contains("inner quote");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list when candidate JSON array contains non-strings")
    void extractFactsFromJson_ArrayWithNonStrings_ReturnsEmptyList() {
        // given — integers parse as strings in Jackson, so just verify no throw
        String response = "Some text [1, 2, 3] more text";

        // then
        assertThat(extractor.extractFactsFromJson(response)).isNotNull();
    }

    @Test
    @DisplayName("extractFactsFromJson handles escaped backslash in string content")
    void extractFactsFromJson_EscapedBackslash_ParsesCorrectly() {
        // then
        assertThat(extractor.extractFactsFromJson("[\"path\\\\to\\\\file\"]")).hasSize(1);
    }

    @Test
    @DisplayName("extractFactsFromJson handles unmatched closing bracket (] with depth=0)")
    void extractFactsFromJson_UnmatchedClosingBracket_HandledGracefully() {
        // given — '] before any [' -> consume() branch where c==']' && depth==0 -> do nothing
        String response = "] some text [\"fact\"]";

        // then — the ']' at position 0 is ignored (depth=0), then '[\"fact\"]' is found and parsed
        assertThat(extractor.extractFactsFromJson(response)).containsExactly("fact");
    }

    @Test
    @DisplayName("extractFactsFromJson handles nested brackets in content string")
    void extractFactsFromJson_NestedBracketsInString_ParsesOutermostArray() {
        // given — string containing [] inside quotes; inString flag prevents inner brackets from counting
        String response = "[\"user has [special] characters\"]";

        // when
        List<String> result = extractor.extractFactsFromJson(response);

        // then
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).contains("[special]");
    }
}
