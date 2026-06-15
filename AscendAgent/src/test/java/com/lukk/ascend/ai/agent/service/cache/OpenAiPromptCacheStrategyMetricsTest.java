package com.lukk.ascend.ai.agent.service.cache;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
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

class OpenAiPromptCacheStrategyMetricsTest {

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.read counter with provider=openai tag")
    void recordOutcome_RegistersTokensReadCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("openai", registry);

        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 512);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.read")
                .tag("provider", "openai")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(512.0);
    }

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.total counter with provider=openai tag")
    void recordOutcome_RegistersTokensTotalCounter() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("openai", registry);

        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 128);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.total")
                .tag("provider", "openai")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isGreaterThan(0.0);
    }

    @Test
    @DisplayName("recordOutcome registers prompt_cache.tokens.read for gemini provider with expected tag")
    void recordOutcome_GeminiProvider_TagsCorrectly() {
        // given
        MeterRegistry registry = new SimpleMeterRegistry();
        OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("gemini", registry);

        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 256);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(50, 512, 562, details, null);
        Usage usage = new DefaultUsage(512, 50, 562, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // when
        strategy.recordOutcome("user", response);

        // then
        Counter counter = registry.find("prompt_cache.tokens.read")
                .tag("provider", "gemini")
                .counter();
        assertThat(counter).isNotNull();
        assertThat(counter.count()).isEqualTo(256.0);
    }
}
