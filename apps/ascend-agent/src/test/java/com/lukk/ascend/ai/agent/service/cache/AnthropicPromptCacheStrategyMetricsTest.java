package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.ai.anthropic.api.AnthropicApi;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AnthropicPromptCacheStrategyMetricsTest {

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.read counter with provider=anthropic tag")
    void recordOutcome_RegistersTokensReadCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        AnthropicPromptCacheStrategy strategy = new AnthropicPromptCacheStrategy(registry);

        AnthropicApi.Usage native_ = new AnthropicApi.Usage(512, 100, 0, 256);
        Usage usage = new DefaultUsage(512, 100, 612, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.read")
                .tag("provider", "anthropic")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(256.0);
    }

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.creation counter with provider=anthropic tag")
    void recordOutcome_RegistersTokensCreationCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        AnthropicPromptCacheStrategy strategy = new AnthropicPromptCacheStrategy(registry);

        AnthropicApi.Usage native_ = new AnthropicApi.Usage(512, 100, 350, 0);
        Usage usage = new DefaultUsage(512, 100, 612, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.creation")
                .tag("provider", "anthropic")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(350.0);
    }

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.total counter with provider=anthropic tag")
    void recordOutcome_RegistersTokensTotalCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        AnthropicPromptCacheStrategy strategy = new AnthropicPromptCacheStrategy(registry);

        AnthropicApi.Usage native_ = new AnthropicApi.Usage(512, 100, 0, 0);
        Usage usage = new DefaultUsage(512, 100, 612, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.total")
                .tag("provider", "anthropic")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isGreaterThanOrEqualTo(0.0);
    }
}
