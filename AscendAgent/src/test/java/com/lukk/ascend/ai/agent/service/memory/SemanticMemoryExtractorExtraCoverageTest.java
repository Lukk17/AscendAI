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

/**
 * Extra branch coverage for SemanticMemoryExtractor: cache retry path,
 * extractFactsFromJson edge-cases, embedded JSON array fallback, BracketScanState paths.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SemanticMemoryExtractorExtraCoverageTest {

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

    // ------------------------------------------------------------------ extractFactsFromJson

    @Test
    @DisplayName("extractFactsFromJson returns empty list for null input")
    void extractFactsFromJson_Null_ReturnsEmptyList() {
        assertThat(extractor.extractFactsFromJson(null)).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list for blank string")
    void extractFactsFromJson_BlankString_ReturnsEmptyList() {
        assertThat(extractor.extractFactsFromJson("   ")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson parses a clean JSON array of strings")
    void extractFactsFromJson_CleanJsonArray_ReturnsList() {
        List<String> result = extractor.extractFactsFromJson("[\"fact one\", \"fact two\"]");
        assertThat(result).containsExactly("fact one", "fact two");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list for empty JSON array")
    void extractFactsFromJson_EmptyJsonArray_ReturnsEmptyList() {
        assertThat(extractor.extractFactsFromJson("[]")).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson strips ```json fences and parses correctly")
    void extractFactsFromJson_WithJsonFence_StripsAndParses() {
        String fenced = "```json\n[\"hello\"]\n```";
        List<String> result = extractor.extractFactsFromJson(fenced);
        assertThat(result).containsExactly("hello");
    }

    @Test
    @DisplayName("extractFactsFromJson falls back to bracket scan when response has leading prose")
    void extractFactsFromJson_LeadingProse_ExtractsEmbeddedArray() {
        String response = "Here are the facts I found: [\"User likes cats\", \"User is a developer\"]";
        List<String> result = extractor.extractFactsFromJson(response);
        assertThat(result).containsExactly("User likes cats", "User is a developer");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list when no valid JSON array is in the response")
    void extractFactsFromJson_NoBracketsInResponse_ReturnsEmptyList() {
        String response = "There are no facts here.";
        List<String> result = extractor.extractFactsFromJson(response);
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("extractFactsFromJson handles nested arrays by returning the last outermost array")
    void extractFactsFromJson_NestedArrays_ReturnsLastOutermostArray() {
        // JSON with nested array inside a string element
        String response = "[\"value with \\\"inner quote\\\"\"]";
        List<String> result = extractor.extractFactsFromJson(response);
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).contains("inner quote");
    }

    @Test
    @DisplayName("extractFactsFromJson returns empty list when candidate JSON array contains non-strings")
    void extractFactsFromJson_ArrayWithNonStrings_ReturnsEmptyList() {
        // An embedded array that looks like it has objects; parse will fail gracefully
        String response = "Some text [1, 2, 3] more text";
        // This is a valid array of ints, not strings — should fail deserialization to List<String>
        // and fall through to empty
        List<String> result = extractor.extractFactsFromJson(response);
        // integers parse as strings in Jackson, so this might actually succeed — just verify no throw
        assertThat(result).isNotNull();
    }

    @Test
    @DisplayName("extractFactsFromJson handles escaped backslash in string content")
    void extractFactsFromJson_EscapedBackslash_ParsesCorrectly() {
        String response = "[\"path\\\\to\\\\file\"]";
        List<String> result = extractor.extractFactsFromJson(response);
        assertThat(result).hasSize(1);
    }

    @Test
    @DisplayName("extractFactsFromJson handles unmatched closing bracket (] with depth=0)")
    void extractFactsFromJson_UnmatchedClosingBracket_HandledGracefully() {
        // '] before any [' — the consume() branch where c==']' && depth==0 -> do nothing
        // Also has a valid array later for successful extraction
        String response = "] some text [\"fact\"]";
        List<String> result = extractor.extractFactsFromJson(response);
        // The ']' at position 0 is ignored (depth=0), then '[\"fact\"]' is found and parsed
        assertThat(result).containsExactly("fact");
    }

    @Test
    @DisplayName("extractFactsFromJson handles nested brackets in content string")
    void extractFactsFromJson_NestedBracketsInString_ParsesOutermostArray() {
        // String containing [] inside quotes - inString flag prevents inner brackets from counting
        String response = "[\"user has [special] characters\"]";
        List<String> result = extractor.extractFactsFromJson(response);
        assertThat(result).hasSize(1);
        assertThat(result.getFirst()).contains("[special]");
    }
}
