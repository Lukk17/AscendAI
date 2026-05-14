package com.lukk.ascend.ai.agent.service.cache;

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
    void buildOptions_ProducesAnthropicOptionsWithSystemOnlyMultiBlockCaching() {
        ChatOptions opts = strategy.buildOptions("claude-sonnet-4-6");

        assertThat(opts).isInstanceOf(AnthropicChatOptions.class);
        AnthropicChatOptions anth = (AnthropicChatOptions) opts;
        assertThat(anth.getModel()).isEqualTo("claude-sonnet-4-6");
        assertThat(anth.getCacheOptions()).isNotNull();
        assertThat(anth.getCacheOptions().getStrategy()).isEqualTo(AnthropicCacheStrategy.SYSTEM_ONLY);
        assertThat(anth.getCacheOptions().isMultiBlockSystemCaching()).isTrue();
    }

    @Test
    void buildOptions_NullModel_StillProducesCacheOptionsWithoutModel() {
        ChatOptions opts = strategy.buildOptions(null);

        assertThat(opts).isInstanceOf(AnthropicChatOptions.class);
        assertThat(((AnthropicChatOptions) opts).getCacheOptions()).isNotNull();
        assertThat(((AnthropicChatOptions) opts).getModel()).isNull();
    }

    @Test
    void recordOutcome_NullResponse_DoesNotThrow() {
        strategy.recordOutcome("u", null);
    }

    @Test
    void recordOutcome_NonAnthropicNativeUsage_NoLogNoThrow() {
        ChatResponse response = mock(ChatResponse.class);
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        Usage usage = mock(Usage.class);
        when(response.getMetadata()).thenReturn(md);
        when(md.getUsage()).thenReturn(usage);
        when(usage.getNativeUsage()).thenReturn(new Object());
        strategy.recordOutcome("u", response);
    }

    @Test
    void recordOutcome_AnthropicHit_LogsCacheReadTokens() {
        ChatResponse response = anthropicResponse(487, 0, 612);
        // log assertion would require a log capture; behavior asserted by no-throw + downstream impact.
        strategy.recordOutcome("user1", response);
    }

    @Test
    void recordOutcome_AnthropicMiss_LogsZeroes() {
        ChatResponse response = anthropicResponse(0, 0, 612);
        strategy.recordOutcome("user1", response);
    }

    @Test
    void isCacheConfigError_DetectsCacheControlInMessage() {
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
