package com.lukk.ascend.ai.agent.service.cache;

import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.DisplayName;
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
    @DisplayName("buildOptions returns generic ChatOptions with the model set for a valid model name")
    void buildOptions_WithModel_ReturnsGenericChatOptions() {
        // when
        ChatOptions opts = strategy.buildOptions("gpt-4o");

        // then
        assertThat(opts).isNotNull();
        assertThat(opts.getModel()).isEqualTo("gpt-4o");
    }

    @Test
    @DisplayName("buildOptions returns null when model is null or blank")
    void buildOptions_NullModel_ReturnsNull() {
        // then
        assertThat(strategy.buildOptions(null)).isNull();
        assertThat(strategy.buildOptions("")).isNull();
    }

    @Test
    @DisplayName("recordOutcome does not throw when response is null")
    void recordOutcome_NullResponse_DoesNotThrow() {
        // then
        strategy.recordOutcome("u", null);
    }

    @Test
    @DisplayName("recordOutcome does not throw when response contains cached prompt tokens")
    void recordOutcome_WithCachedTokens_DoesNotThrow() {
        // given
        OpenAiApi.Usage.PromptTokensDetails details = new OpenAiApi.Usage.PromptTokensDetails(0, 512);
        OpenAiApi.Usage native_ = new OpenAiApi.Usage(100, 1024, 1124, details, null);
        Usage usage = new DefaultUsage(1024, 100, 1124, native_);
        ChatResponseMetadata md = ChatResponseMetadata.builder().usage(usage).build();
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("recordOutcome does not throw when native usage type is not OpenAiApi.Usage")
    void recordOutcome_NoNativeUsage_DoesNotThrow() {
        // given
        Usage usage = mock(Usage.class);
        when(usage.getNativeUsage()).thenReturn(new Object());
        ChatResponseMetadata md = mock(ChatResponseMetadata.class);
        when(md.getUsage()).thenReturn(usage);
        ChatResponse response = mock(ChatResponse.class);
        when(response.getMetadata()).thenReturn(md);

        // then
        strategy.recordOutcome(TestConstants.DEFAULT_USER_ID, response);
    }

    @Test
    @DisplayName("providerName returns the value passed to the constructor")
    void providerName_IsConstructorArg() {
        // then
        assertThat(new OpenAiPromptCacheStrategy("openai").providerName()).isEqualTo("openai");
        assertThat(new OpenAiPromptCacheStrategy("gemini").providerName()).isEqualTo("gemini");
    }
}
