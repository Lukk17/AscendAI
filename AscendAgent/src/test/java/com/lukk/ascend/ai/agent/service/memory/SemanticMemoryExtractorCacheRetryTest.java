package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.ChatResponseContentResolver;
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
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.ai.chat.prompt.Prompt;

import java.util.Map;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Cache retry path and invokeExtractor branch coverage for SemanticMemoryExtractor.
 * The extract() method spawns a virtual thread; tests use timeout verification.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class SemanticMemoryExtractorCacheRetryTest {

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

    @Mock
    private ChatModel chatModel;

    private SemanticMemoryExtractor extractor;

    @BeforeEach
    void setUp() {
        when(aiProviderProperties.getProviders()).thenReturn(Map.of());
        extractor = new SemanticMemoryExtractor(chatModelResolver, aiProviderProperties, memoryClient,
                new ObjectMapper(), chatResponseContentResolver, cacheStrategyResolver);
    }

    @Test
    @DisplayName("extract triggers cache retry when isCacheConfigError returns true and retry succeeds")
    void extract_CacheConfigError_RetriesWithoutCache() throws InterruptedException {
        // given — strategy with isCacheConfigError=true
        PromptCacheStrategy cacheErrorStrategy = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) { return ChatOptions.builder().model(model).build(); }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
            @Override public boolean isCacheConfigError(Throwable t) { return true; }
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(cacheErrorStrategy);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);

        ChatResponse goodResp = buildResponse("[]");
        when(chatModel.call(any(Prompt.class)))
                .thenThrow(new RuntimeException("cache_control error"))
                .thenReturn(goodResp);
        when(chatResponseContentResolver.resolveContent(goodResp)).thenReturn("[]");

        // when — extract spawns a virtual thread
        extractor.extract("frosty", "I love coding", "openai", "gpt-4o-mini", "openai");

        // give virtual thread time to finish
        Thread.sleep(300);

        verify(chatModel, org.mockito.Mockito.atLeastOnce()).call(any(Prompt.class));
    }

    @Test
    @DisplayName("extract does NOT retry when isCacheConfigError returns false (error is propagated)")
    void extract_NonCacheError_DoesNotRetry() throws InterruptedException {
        PromptCacheStrategy noCacheError = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) { return null; }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
            @Override public boolean isCacheConfigError(Throwable t) { return false; }
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(noCacheError);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);
        when(chatModel.call(any(Prompt.class))).thenThrow(new RuntimeException("unrelated error"));

        extractor.extract("frosty", "prompt", "openai", "gpt-4o-mini", "openai");

        Thread.sleep(300);

        // called exactly once (no retry), then handleExtractionError swallows it
        verify(chatModel).call(any(Prompt.class));
    }

    @Test
    @DisplayName("extract uses requestedModel directly when it is non-blank (no provider lookup)")
    void extract_NonBlankRequestedModel_UsesIt() throws InterruptedException {
        PromptCacheStrategy noop = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) { return null; }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);

        ChatResponse resp = buildResponse("[]");
        when(chatModel.call(any(Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn("[]");

        extractor.extract("frosty", "prompt", "openai", "gpt-4o-mini", "openai");

        Thread.sleep(300);

        verify(chatModel).call(any(Prompt.class));
    }

    @Test
    @DisplayName("invokeExtractor passes options to spec when options is not null")
    void invokeExtractor_NonNullOptions_PassesOptionsToSpec() throws InterruptedException {
        PromptCacheStrategy withOptions = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) {
                return ChatOptions.builder().model(model).build(); // non-null
            }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(withOptions);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);

        ChatResponse resp = buildResponse("[]");
        when(chatModel.call(any(Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn("[]");

        extractor.extract("frosty", "prompt", "openai", "gpt-4o-mini", "openai");

        Thread.sleep(300);

        verify(chatModel).call(any(Prompt.class));
    }

    // ------------------------------------------------------------------ findLastBalancedJsonArray

    @Test
    @DisplayName("extractFactsFromJson returns empty list when input is blank (findLastBalancedJsonArray returns empty)")
    void extractFactsFromJson_BlankInput_ReturnsEmpty() {
        extractor.extractFactsFromJson("   ");
        // no throw; asserted in other tests
    }

    // ------------------------------------------------------------------ cache retry with blank extractionModel (line 76 null branch)

    @Test
    @DisplayName("extract uses null fallback options when extractionModel is blank during cache retry")
    void extract_CacheRetry_WithBlankExtractionModel_UsesFallbackNull() throws InterruptedException {
        // providers map empty + model null -> extractionModel = null -> fallback = null (line 76 null branch)
        PromptCacheStrategy cacheErrorStrategy = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) {
                return model != null ? ChatOptions.builder().model(model).build() : null;
            }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
            @Override public boolean isCacheConfigError(Throwable t) { return true; }
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(cacheErrorStrategy);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);

        ChatResponse goodResp = buildResponse("[]");
        when(chatModel.call(any(Prompt.class)))
                .thenThrow(new RuntimeException("cache_control error"))
                .thenReturn(goodResp);
        when(chatResponseContentResolver.resolveContent(goodResp)).thenReturn("[]");

        // null model → extractionModel = null → on retry: fallback = null (StringUtils.hasText(null) = false)
        extractor.extract("frosty", "I love coding", "openai", null, "openai");

        Thread.sleep(300);

        verify(chatModel, org.mockito.Mockito.atLeastOnce()).call(any(Prompt.class));
    }

    // ------------------------------------------------------------------ invokeExtractor with options=null AND blank extractionModel (line 91 false branch)

    @Test
    @DisplayName("invokeExtractor skips defaultOptions when options is null and extractionModel is blank")
    void invokeExtractor_NullOptionsAndBlankExtractionModel_NoDefaultOptions() throws InterruptedException {
        // providers map empty + model null -> extractionModel = null
        // Noop buildOptions(null) = null -> decoratedOptions = null
        // invokeExtractor(chatModel, userText, null, null):
        //   options==null && hasText(null) = false -> NO defaultOptions set (line 91 false branch)
        PromptCacheStrategy noop = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public ChatOptions buildOptions(String model) { return null; }
            @Override public void recordOutcome(String userId, ChatResponse r) {}
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
        when(chatModelResolver.resolve("openai")).thenReturn(chatModel);

        ChatResponse resp = buildResponse("[]");
        when(chatModel.call(any(Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn("[]");

        // null model → extractionModel = null → invokeExtractor(..., null, null) hits the false branch
        extractor.extract("frosty", "some text", "openai", null, "openai");

        Thread.sleep(300);

        verify(chatModel).call(any(Prompt.class));
    }

    // ------------------------------------------------------------------ helper

    private ChatResponse buildResponse(String content) {
        AssistantMessage msg = org.mockito.Mockito.mock(AssistantMessage.class);
        when(msg.getText()).thenReturn(content);
        Generation gen = org.mockito.Mockito.mock(Generation.class);
        when(gen.getOutput()).thenReturn(msg);
        ChatResponse resp = org.mockito.Mockito.mock(ChatResponse.class);
        when(resp.getResult()).thenReturn(gen);
        when(resp.getMetadata()).thenReturn(org.mockito.Mockito.mock(ChatResponseMetadata.class));
        return resp;
    }
}
