package com.lukk.ascend.ai.agent.service.cache;

import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.DefaultUsage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class OpenAiPromptCacheStrategyTest {

    private final OpenAiPromptCacheStrategy strategy = new OpenAiPromptCacheStrategy("openai");

    @Test
    void buildOptions_WithModel_ReturnsGenericChatOptions() {
        ChatOptions opts = strategy.buildOptions("gpt-4o");
        assertThat(opts).isNotNull();
        assertThat(opts.getModel()).isEqualTo("gpt-4o");
    }

    @Test
    void buildOptions_NullModel_ReturnsNull() {
        assertThat(strategy.buildOptions(null)).isNull();
        assertThat(strategy.buildOptions("")).isNull();
    }

    @Test
    void recordOutcome_NullResponse_DoesNotThrow() {
        strategy.recordOutcome("u", null);
    }

    @Test
    void recordOutcome_WithCachedTokens_DoesNotThrow() {
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 512);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        strategy.recordOutcome("user1", response);
    }

    @Test
    void recordOutcome_NoNativeUsage_DoesNotThrow() {
        Usage usage = mock(Usage.class);
        when(usage.getNativeUsage()).thenReturn(new Object());
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(usage);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        strategy.recordOutcome("user1", response);
    }

    @Test
    void providerName_IsConstructorArg() {
        assertThat(new OpenAiPromptCacheStrategy("openai").providerName()).isEqualTo("openai");
        assertThat(new OpenAiPromptCacheStrategy("gemini").providerName()).isEqualTo("gemini");
    }
}
