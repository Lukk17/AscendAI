package com.lukk.ascend.ai.agent.service.cache;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.openai.api.OpenAiApi;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for OpenAiPromptCacheStrategy:
 *  - recordOutcome with null usage
 *  - recordOutcome when PromptTokensDetails is null
 *  - recordOutcome when cachedTokens is 0 (cold-start)
 */
class OpenAiPromptCacheStrategyExtraTest {

    private final OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("openai");

    @Test
    @DisplayName("recordOutcome does not throw when usage is null")
    void recordOutcome_NullUsage_DoesNotThrow() {
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(null);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        strategy.recordOutcome("user", response);
    }

    @Test
    @DisplayName("recordOutcome does not throw when PromptTokensDetails is null inside OpenAiApi.Usage")
    void recordOutcome_NullPromptTokensDetails_DoesNotThrow() {
        // OpenAiApi.Usage with null PromptTokensDetails
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, null, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // should return early without logging (cachedTokens == null -> extractCachedTokens returns null)
        strategy.recordOutcome("user", response);
    }

    @Test
    @DisplayName("recordOutcome logs cold-start when cachedTokens is 0")
    void recordOutcome_CachedTokensZero_LogsColdStart() {
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 0);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // must not throw; logs hit=false
        strategy.recordOutcome("user", response);
    }

    @Test
    @DisplayName("buildOptions returns null when model is an empty string")
    void buildOptions_EmptyModel_ReturnsNull() {
        assertThat(strategy.buildOptions("")).isNull();
    }

    @Test
    @DisplayName("buildOptions returns null when model is whitespace")
    void buildOptions_WhitespaceModel_ReturnsNull() {
        assertThat(strategy.buildOptions("   ")).isNull();
    }

    @Test
    @DisplayName("recordOutcome uses 0 for prompt tokens when getPromptTokens() returns null (mocked Usage)")
    void recordOutcome_MockedUsageWithNullPromptTokens_UsesZero() {
        // DefaultUsage converts null to 0 internally, so getPromptTokens() is never null from DefaultUsage.
        // Use a mocked Usage to get truly null from getPromptTokens() (covers the null branch of the ternary).
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 128);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = mock(Usage.class);
        when(usage.getNativeUsage()).thenReturn(native_);
        when(usage.getPromptTokens()).thenReturn(null); // truly null
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(usage);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // must not throw; uses 0 for prompt_tokens (null ternary branch)
        strategy.recordOutcome("user", response);
    }
}
