package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.model.ChatResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class NoopPromptCacheStrategyTest {

    @Test
    @DisplayName("buildOptions returns null when model is null")
    void buildOptions_NullModel_ReturnsNull() {
        // given
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("lmstudio", new SimpleMeterRegistry());

        // then
        assertThat(strategy.buildOptions(null)).isNull();
    }

    @Test
    @DisplayName("buildOptions returns generic ChatOptions with the model set")
    void buildOptions_WithModel_ReturnsGenericChatOptionsWithModel() {
        // given
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("minimax", new SimpleMeterRegistry());

        // when
        var opts = strategy.buildOptions("MiniMax-M2.5");

        // then
        assertThat(opts).isNotNull();
        assertThat(opts.getModel()).isEqualTo("MiniMax-M2.5");
    }

    @Test
    @DisplayName("recordOutcome emits gen_ai.client.token.usage counter for null response gracefully")
    void recordOutcome_NullResponse_DoesNotThrow() {
        // then — must not throw; null response is silently skipped
        new NoopPromptCacheStrategy("x", new SimpleMeterRegistry()).recordOutcome("u", null);
    }

    @Test
    @DisplayName("recordOutcome emits gen_ai.client.token.usage counter for lmstudio provider")
    void recordOutcome_WithUsage_EmitsGenAiTokenUsageCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        NoopPromptCacheStrategy strategy = new NoopPromptCacheStrategy("lmstudio", registry);

        DefaultUsage usage = new DefaultUsage(100, 50, 150, null);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("u", response);

        // then
        Counter inputCounter = registry.find("gen_ai.client.token.usage")
                .tag("gen_ai_system", "lmstudio")
                .tag("gen_ai_token_type", "input")
                .counter();
        assertThat(inputCounter).isNotNull();
        assertThat(inputCounter.count()).isEqualTo(100.0);
    }

    @Test
    @DisplayName("isCacheConfigError always returns false regardless of exception")
    void isCacheConfigError_AlwaysFalse() {
        // then
        assertThat(new NoopPromptCacheStrategy("x", new SimpleMeterRegistry())
                .isCacheConfigError(new RuntimeException("cache_control bad"))).isFalse();
    }
}
