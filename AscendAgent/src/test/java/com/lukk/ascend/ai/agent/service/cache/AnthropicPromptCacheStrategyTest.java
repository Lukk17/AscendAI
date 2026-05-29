package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.anthropic.AnthropicChatOptions;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.anthropic.api.AnthropicCacheStrategy;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnthropicPromptCacheStrategyTest {

    private final AnthropicPromptCacheStrategy strategy = new AnthropicPromptCacheStrategy();

    @Test
    @DisplayName("buildOptions produces AnthropicChatOptions with SYSTEM_ONLY multi-block caching")
    void buildOptions_ProducesAnthropicOptionsWithSystemOnlyMultiBlockCaching() {
        // when
        ChatOptions opts = strategy.buildOptions("claude-sonnet-4-6");

        // then
        assertThat(opts).isInstanceOf(AnthropicChatOptions.class);
        AnthropicChatOptions anth = (AnthropicChatOptions) opts;
        assertThat(anth.getModel()).isEqualTo("claude-sonnet-4-6");
        assertThat(anth.getCacheOptions()).isNotNull();
        assertThat(anth.getCacheOptions().getStrategy()).isEqualTo(AnthropicCacheStrategy.SYSTEM_ONLY);
        assertThat(anth.getCacheOptions().isMultiBlockSystemCaching()).isTrue();
    }

    @Test
    @DisplayName("buildOptions produces cache options without a model when null model is passed")
    void buildOptions_NullModel_StillProducesCacheOptionsWithoutModel() {
        // when
        ChatOptions opts = strategy.buildOptions(null);

        // then
        assertThat(opts).isInstanceOf(AnthropicChatOptions.class);
        assertThat(((AnthropicChatOptions) opts).getCacheOptions()).isNotNull();
        assertThat(((AnthropicChatOptions) opts).getModel()).isNull();
    }

    @Test
    @DisplayName("recordOutcome does not throw when response is null")
    void recordOutcome_NullResponse_DoesNotThrow() {
        // then
        strategy.recordOutcome("u", null);
    }

    @Test
    @DisplayName("recordOutcome does not throw when native usage is not AnthropicApi.Usage")
    void recordOutcome_NonAnthropicNativeUsage_NoLogNoThrow() {
        // given
        ChatResponse response = mock(ChatResponse.class);
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        Usage usage = mock(Usage.class);
        when(response.getMetadata()).thenReturn(md);
        when(md.getUsage()).thenReturn(usage);
        when(usage.getNativeUsage()).thenReturn(new Object());

        // then
        strategy.recordOutcome("u", response);
    }

    @Test
    @DisplayName("recordOutcome logs cache read tokens on a cache hit")
    void recordOutcome_AnthropicHit_LogsCacheReadTokens() {
        // given — cache hit: cacheRead > 0, cacheCreate == 0
        ChatResponse response = anthropicResponse(487, 0, 612);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("recordOutcome logs zeroes on a cold-start cache miss")
    void recordOutcome_AnthropicMiss_LogsZeroes() {
        // given — cold start: both cacheRead and cacheCreate are 0
        ChatResponse response = anthropicResponse(0, 0, 612);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("recordOutcome logs cacheCreate tokens on first cache population (write only)")
    void recordOutcome_AnthropicWrite_LogsCacheCreateTokens() {
        // given — cache write: cacheCreate > 0, cacheRead == 0 (first population of cache)
        ChatResponse response = anthropicResponse(0, 350, 612);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("recordOutcome handles both cacheRead and cacheCreate being non-zero in a partial hit")
    void recordOutcome_AnthropicHitAndWrite_BothNonZero() {
        // given — mixed: cache was partially warmed so both counters > 0
        ChatResponse response = anthropicResponse(312, 100, 1024);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("isCacheConfigError detects cache_control error messages and ignores unrelated ones")
    void isCacheConfigError_DetectsCacheControlInMessage() {
        // then
        assertThat(strategy.isCacheConfigError(new RuntimeException("400 invalid cache_control block"))).isTrue();
        assertThat(strategy.isCacheConfigError(new RuntimeException("HTTP 400 cache-control malformed"))).isTrue();
        assertThat(strategy.isCacheConfigError(new RuntimeException("401 unauthorized"))).isFalse();
        assertThat(strategy.isCacheConfigError(null)).isFalse();
        assertThat(strategy.isCacheConfigError(new RuntimeException((String) null))).isFalse();
    }

    private ChatResponse anthropicResponse(int cacheRead, int cacheCreate, int promptTokens) {
        AnthropicApi.Usage native_ = new AnthropicApi.Usage(promptTokens, 100, cacheCreate, cacheRead);
        Usage usage = new DefaultUsage(promptTokens, 100, promptTokens + 100, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);
        return response;
    }
}
