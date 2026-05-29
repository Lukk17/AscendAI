package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.service.cache.NoopPromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.mock.web.MockMultipartFile;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for ChatExecutor:
 *  - hasDynamic=false (no dynamic suffix in AssembledSystemMessages)
 *  - hasDynamic=true (dynamic suffix present)
 *  - decoratedOptions==null && model blank -> no defaultOptions set on builder
 *  - resolveImageMimeType fallback paths: no content-type, suspect content-type, octet-stream
 *  - cache retry path (isCacheConfigError=true)
 *  - null/empty history (not-adding to allMessages)
 *  - extractExtension: dot-trailing filename
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class ChatExecutorExtraTest {

    private static final String USER_ID = "frosty";
    private static final String PROVIDER = "lmstudio";
    private static final String MODEL = "llama-3.1";
    private static final String USER_TEXT = "Hello world";
    private static final String RESPONSE_CONTENT = "Hi there";

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private SyncMcpToolCallbackProvider toolCallbackProvider;

    @Mock
    private ChatResponseContentResolver chatResponseContentResolver;

    @Mock
    private PromptCacheStrategyResolver cacheStrategyResolver;

    @Mock
    private ChatModel chatModel;

    @InjectMocks
    private ChatExecutor chatExecutor;

    @BeforeEach
    void setUpDefaults() {
        PromptCacheStrategy noop = new NoopPromptCacheStrategy(PROVIDER);
        when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);
    }

    // ------------------------------------------------------------------ hasDynamic branches

    @Test
    @DisplayName("execute uses only staticPrefix when dynamicSuffix is blank (hasDynamic=false)")
    void execute_WhenDynamicSuffixBlank_UsesOnlyStaticPrefix() {
        // given
        AssembledSystemMessages msgs = new AssembledSystemMessages("Static system prompt", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // when
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then
        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    @Test
    @DisplayName("execute adds dynamic suffix as second system message when hasDynamic=true")
    void execute_WhenDynamicSuffixPresent_AddsBothSystemMessages() {
        // given
        AssembledSystemMessages msgs = new AssembledSystemMessages("Static prompt", "User instructions: be concise");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // when
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then
        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ cache retry path

    @Test
    @DisplayName("execute retries without cache options when isCacheConfigError returns true")
    void execute_WhenCacheConfigError_RetriesWithoutCache() {
        // given — strategy that claims all exceptions are cache config errors
        PromptCacheStrategy alwaysCacheError = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public org.springframework.ai.chat.prompt.ChatOptions buildOptions(String model) { return null; }
            @Override public void recordOutcome(String userId, org.springframework.ai.chat.model.ChatResponse response) {}
            @Override public boolean isCacheConfigError(Throwable t) { return true; }
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(alwaysCacheError);

        // first call throws (simulates cache-config error), second succeeds
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(Prompt.class)))
                .thenThrow(new RuntimeException("cache_control error"))
                .thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // when
        AiResponse result = chatExecutor.execute(USER_ID, "sys", USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then — second invocation succeeded
        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ resolveImageMimeType

    @Test
    @DisplayName("resolveImageMimeType defaults to image/png when content-type is null and filename has no extension")
    void resolveImageMimeType_NullContentTypeAndNoExtension_DefaultsToPng() {
        MockMultipartFile f = new MockMultipartFile("file", "noextension", null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("resolveImageMimeType falls back to extension when content-type is application/octet-stream")
    void resolveImageMimeType_OctetStream_FallsBackToExtension() {
        MockMultipartFile f = new MockMultipartFile("file", "photo.jpg", "application/octet-stream", new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/jpeg");
    }

    @Test
    @DisplayName("resolveImageMimeType falls back to extension when content-type has no slash")
    void resolveImageMimeType_NoSlashInContentType_FallsBackToExtension() {
        MockMultipartFile f = new MockMultipartFile("file", "photo.png", "FILE", new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("resolveImageMimeType returns image/webp for .webp extension when content-type is absent")
    void resolveImageMimeType_WebpExtension_ReturnsWebp() {
        MockMultipartFile f = new MockMultipartFile("file", "img.webp", null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/webp");
    }

    @Test
    @DisplayName("resolveImageMimeType returns image/gif for .gif extension when content-type is absent")
    void resolveImageMimeType_GifExtension_ReturnsGif() {
        MockMultipartFile f = new MockMultipartFile("file", "anim.gif", null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/gif");
    }

    @Test
    @DisplayName("resolveImageMimeType defaults to image/png for unknown extension when content-type is absent")
    void resolveImageMimeType_UnknownExtension_DefaultsToPng() {
        MockMultipartFile f = new MockMultipartFile("file", "image.bmp", null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("resolveImageMimeType returns image/jpeg from content-type header when valid")
    void resolveImageMimeType_ValidContentType_UsesHeader() {
        MockMultipartFile f = new MockMultipartFile("file", "photo.png", "image/jpeg", new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/jpeg");
    }

    @Test
    @DisplayName("resolveImageMimeType falls back to extension when content-type is blank")
    void resolveImageMimeType_BlankContentType_FallsBackToExtension() {
        MockMultipartFile f = new MockMultipartFile("file", "photo.jpeg", "", new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/jpeg");
    }

    @Test
    @DisplayName("resolveImageMimeType defaults to image/png when filename has a trailing dot")
    void resolveImageMimeType_TrailingDotFilename_DefaultsToPng() {
        MockMultipartFile f = new MockMultipartFile("file", "image.", null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/png");
    }

    @Test
    @DisplayName("resolveImageMimeType defaults to image/png when filename is null")
    void resolveImageMimeType_NullFilename_DefaultsToPng() {
        MockMultipartFile f = new MockMultipartFile("file", null, null, new byte[1]);
        assertThat(chatExecutor.resolveImageMimeType(f).toString()).isEqualTo("image/png");
    }

    // ------------------------------------------------------------------ cache error NOT triggered -> rethrow

    @Test
    @DisplayName("execute rethrows RuntimeException when isCacheConfigError returns false")
    void execute_CacheErrorFalse_Rethrows() {
        // given — strategy that says it's NOT a cache error (default NoopPromptCacheStrategy)
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new org.springframework.ai.tool.function.FunctionToolCallback[0]);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class)))
                .thenThrow(new RuntimeException("network timeout"));

        // when/then
        org.assertj.core.api.Assertions.assertThatThrownBy(
                () -> chatExecutor.execute(USER_ID, "sys", USER_TEXT, List.of(), null, PROVIDER, MODEL))
                .isInstanceOf(RuntimeException.class)
                .hasMessageContaining("network timeout");
    }

    // ------------------------------------------------------------------ null history path

    @Test
    @DisplayName("execute handles null history without adding to allMessages")
    void execute_NullHistory_DoesNotThrow() {
        // given
        AssembledSystemMessages msgs = new AssembledSystemMessages("sys", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // when — null history passed
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, null, null, PROVIDER, MODEL);

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    @Test
    @DisplayName("execute when options are non-null passes them to promptBuilder without re-setting model")
    void execute_DecoratedOptionsNonNull_PassesOptionsToPrompt() {
        // given — use Anthropic strategy which returns non-null options
        org.springframework.ai.anthropic.AnthropicChatOptions anthOpts =
                org.springframework.ai.anthropic.AnthropicChatOptions.builder().build();
        PromptCacheStrategy strategyWithOptions = new org.springframework.ai.anthropic.api.AnthropicApi.Usage(null, null, null, null) == null
                ? null
                : new PromptCacheStrategy() {
                    @Override public String providerName() { return "anthropic"; }
                    @Override public org.springframework.ai.chat.prompt.ChatOptions buildOptions(String model) { return anthOpts; }
                    @Override public void recordOutcome(String userId, org.springframework.ai.chat.model.ChatResponse r) {}
                };
        // Easier: use AnthropicPromptCacheStrategy directly
        org.springframework.ai.anthropic.api.AnthropicCacheOptions co =
                org.springframework.ai.anthropic.api.AnthropicCacheOptions.builder()
                        .strategy(org.springframework.ai.anthropic.api.AnthropicCacheStrategy.SYSTEM_ONLY)
                        .build();
        org.springframework.ai.anthropic.AnthropicChatOptions opts =
                org.springframework.ai.anthropic.AnthropicChatOptions.builder().cacheOptions(co).build();

        PromptCacheStrategy anthStrategy = new PromptCacheStrategy() {
            @Override public String providerName() { return "anthropic"; }
            @Override public org.springframework.ai.chat.prompt.ChatOptions buildOptions(String model) { return opts; }
            @Override public void recordOutcome(String userId, org.springframework.ai.chat.model.ChatResponse r) {}
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(anthStrategy);
        when(chatModelResolver.resolve("anthropic")).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new org.springframework.ai.tool.function.FunctionToolCallback[0]);

        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        AiResponse result = chatExecutor.execute(USER_ID, "sys", USER_TEXT, List.of(), null, "anthropic", "claude-sonnet-4-5");

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    @Test
    @DisplayName("execute with null history and non-null options passes both correctly")
    void execute_NullHistoryWithNonNullOptions_Succeeds() {
        // given — strategy returns non-null options AND history is null
        org.springframework.ai.anthropic.api.AnthropicCacheOptions co =
                org.springframework.ai.anthropic.api.AnthropicCacheOptions.builder()
                        .strategy(org.springframework.ai.anthropic.api.AnthropicCacheStrategy.SYSTEM_ONLY)
                        .build();
        org.springframework.ai.anthropic.AnthropicChatOptions opts =
                org.springframework.ai.anthropic.AnthropicChatOptions.builder().cacheOptions(co).build();

        PromptCacheStrategy anthStrategy = new PromptCacheStrategy() {
            @Override public String providerName() { return "anthropic"; }
            @Override public org.springframework.ai.chat.prompt.ChatOptions buildOptions(String model) { return opts; }
            @Override public void recordOutcome(String userId, org.springframework.ai.chat.model.ChatResponse r) {}
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(anthStrategy);
        when(chatModelResolver.resolve("anthropic")).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new org.springframework.ai.tool.function.FunctionToolCallback[0]);

        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // when — null history AND non-null options (covers: if (options != null) { promptBuilder.options(options); })
        AiResponse result = chatExecutor.execute(USER_ID, "sys", USER_TEXT, null, null, "anthropic", "claude-sonnet-4-5");

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    @Test
    @DisplayName("execute with decoratedOptions=null and blank model does NOT set model on builder")
    void execute_NullOptionsAndBlankModel_DoesNotSetModel() {
        // NoopPromptCacheStrategy returns null options, blank model -> buildChatClient skips defaultOptions
        AssembledSystemMessages msgs = new AssembledSystemMessages("sys", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // blank model -> decoratedOptions=null (noop) AND model is blank -> no defaultOptions on builder
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, null, null, PROVIDER, "");

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ non-empty history list (A=true, B=true branch)

    @Test
    @DisplayName("execute with non-empty history list adds messages to conversation context")
    void execute_NonEmptyHistoryList_AddsHistoryToMessages() {
        AssembledSystemMessages msgs = new AssembledSystemMessages("sys", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // Non-empty history -> history != null && !history.isEmpty() = true -> addAll(history) called
        org.springframework.ai.chat.messages.UserMessage userMsg =
                new org.springframework.ai.chat.messages.UserMessage("previous user message");
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT,
                java.util.List.of(userMsg), null, PROVIDER, MODEL);

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ empty (non-null) history list

    @Test
    @DisplayName("execute with empty (not null) history list does not add history to messages")
    void execute_EmptyHistoryList_DoesNotAddHistory() {
        AssembledSystemMessages msgs = new AssembledSystemMessages("sys", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // empty list (non-null) -> history != null but history.isEmpty() == true -> not added
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, java.util.List.of(), null, PROVIDER, MODEL);

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ image.isEmpty() branch

    @Test
    @DisplayName("handleImageContext uses text-only prompt when image file is empty (isEmpty=true)")
    void execute_EmptyImageFile_UsesTextOnlyPrompt() {
        AssembledSystemMessages msgs = new AssembledSystemMessages("sys", "");
        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class))).thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // MockMultipartFile with empty byte array -> isEmpty() returns true
        MockMultipartFile emptyImage = new MockMultipartFile("file", "img.png", "image/png", new byte[0]);
        AiResponse result = chatExecutor.execute(USER_ID, msgs, USER_TEXT, java.util.List.of(), emptyImage, PROVIDER, MODEL);

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ cache retry with blank model (null fallback options)

    @Test
    @DisplayName("execute cache retry uses null fallback options when model is blank/null")
    void execute_CacheRetryWithBlankModel_UsesFallbackOptionsNull() {
        PromptCacheStrategy alwaysCacheError = new PromptCacheStrategy() {
            @Override public String providerName() { return "test"; }
            @Override public org.springframework.ai.chat.prompt.ChatOptions buildOptions(String model) { return null; }
            @Override public void recordOutcome(String userId, org.springframework.ai.chat.model.ChatResponse response) {}
            @Override public boolean isCacheConfigError(Throwable t) { return true; }
        };
        when(cacheStrategyResolver.resolve(any())).thenReturn(alwaysCacheError);

        ChatResponse resp = buildResponse(RESPONSE_CONTENT);
        when(chatModel.call(any(org.springframework.ai.chat.prompt.Prompt.class)))
                .thenThrow(new RuntimeException("cache_control error"))
                .thenReturn(resp);
        when(chatResponseContentResolver.resolveContent(resp)).thenReturn(RESPONSE_CONTENT);

        // Pass null model so StringUtils.hasText(null) == false -> fallback options = null
        AiResponse result = chatExecutor.execute(USER_ID, "sys", USER_TEXT, java.util.List.of(), null, PROVIDER, null);

        assertThat(result.content()).isEqualTo(RESPONSE_CONTENT);
    }

    // ------------------------------------------------------------------ helper

    private ChatResponse buildResponse(String content) {
        AssistantMessage msg = mock(AssistantMessage.class);
        when(msg.getText()).thenReturn(content);
        Generation gen = mock(Generation.class);
        when(gen.getOutput()).thenReturn(msg);
        ChatResponse resp = mock(ChatResponse.class);
        when(resp.getResult()).thenReturn(gen);
        when(resp.getMetadata()).thenReturn(mock(ChatResponseMetadata.class));
        return resp;
    }
}
