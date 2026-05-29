package com.lukk.ascend.ai.agent.service.chat;
import com.lukk.ascend.ai.agent.service.provider.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.provider.ChatModelResolver;

import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.exception.AiGenerationException;
import com.lukk.ascend.ai.agent.service.cache.NoopPromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import com.lukk.ascend.ai.agent.test.TestConstants;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.function.FunctionToolCallback;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatExecutorTest {

    private static final String DEFAULT_USER_ID = TestConstants.DEFAULT_USER_ID;
    private static final String SYSTEM_TEXT = "You are AI";
    private static final String USER_TEXT = "Hello";
    private static final String PROVIDER = "lmstudio";
    private static final String MODEL = "meta-llama-3.1";
    private static final String EXPECTED_RESPONSE = "Hi there";

    @Mock
    private ChatModelResolver chatModelResolver;

    @Mock
    private SyncMcpToolCallbackProvider toolCallbackProvider;

    @Mock
    private ChatResponseContentResolver chatResponseContentResolver;

    @Mock
    private ChatModel chatModel;

    @Mock
    private PromptCacheStrategyResolver cacheStrategyResolver;

    @InjectMocks
    private ChatExecutor chatExecutor;

    @BeforeEach
    void setupGlobalFields() {
        PromptCacheStrategy noop = new NoopPromptCacheStrategy("lmstudio");
        org.mockito.Mockito.lenient().when(cacheStrategyResolver.resolve(any())).thenReturn(noop);
    }

    @Test
    @DisplayName("execute returns AiResponse with empty tools list when no tool calls are present")
    void execute_WhenValidInput_ThenReturnsAiResponse() {
        // given
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        ChatResponse mockResponse = createMockChatResponse(EXPECTED_RESPONSE, null);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(EXPECTED_RESPONSE);

        // when
        AiResponse result = chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then
        assertThat(result).isNotNull();
        assertThat(result.content()).isEqualTo(EXPECTED_RESPONSE);
        assertThat(result.metadata().toolsUsed()).isEmpty();
    }

    @Test
    @DisplayName("execute returns tool names in metadata when the model invoked tools")
    void execute_WhenToolsInvoked_ThenReturnsToolsInMetadata() {
        // given
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        AssistantMessage.ToolCall toolCall = new AssistantMessage.ToolCall(
                "1", TestConstants.TEST_TOOL_NAME, TestConstants.TEST_TOOL_NAME, "{}");
        ChatResponse mockResponse = createMockChatResponse(EXPECTED_RESPONSE, List.of(toolCall));
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(EXPECTED_RESPONSE);

        // when
        AiResponse result = chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then
        assertThat(result.content()).isEqualTo(EXPECTED_RESPONSE);
        assertThat(result.metadata().toolsUsed()).containsExactly(TestConstants.TEST_TOOL_NAME);
    }

    @Test
    @DisplayName("execute embeds image as media when an image is attached to the request")
    void execute_WhenImageAttached_ThenEmbedsMediaSuccessfully() {
        // given
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        MockMultipartFile image = new MockMultipartFile("file", "cat.png", "image/png", "img_data".getBytes());
        ChatResponse mockResponse = createMockChatResponse(EXPECTED_RESPONSE, null);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(EXPECTED_RESPONSE);

        // when
        AiResponse result = chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), image, PROVIDER, MODEL);

        // then
        assertThat(result.content()).isEqualTo(EXPECTED_RESPONSE);
    }

    @Test
    @DisplayName("execute returns actual content from the last generation when model produces thinking output")
    void execute_WhenThinkingModel_ThenReturnsActualContent() {
        // given
        String thinkingText = "Let me analyze this step by step...";
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        ChatResponse mockResponse = createMockChatResponse(thinkingText, null);
        when(chatModel.call(any(Prompt.class))).thenReturn(mockResponse);
        when(chatResponseContentResolver.resolveContent(mockResponse)).thenReturn(EXPECTED_RESPONSE);

        // when
        AiResponse result = chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), null, PROVIDER, MODEL);

        // then
        assertThat(result.content()).isEqualTo(EXPECTED_RESPONSE);
    }

    @Test
    @DisplayName("execute throws AiGenerationException when image processing fails with IOException")
    void execute_WhenImageProcessingFails_ThenThrowsAiGenerationException() throws IOException {
        // given
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        MultipartFile mockImage = mock(MultipartFile.class);
        when(mockImage.isEmpty()).thenReturn(false);
        when(mockImage.getInputStream()).thenThrow(new IOException("Corrupted IO"));

        // then
        assertThatThrownBy(() -> chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), mockImage, PROVIDER, MODEL))
                .isInstanceOf(AiGenerationException.class)
                .hasMessageContaining("Failed to process image upload");
    }

    @Test
    @DisplayName("execute throws AiGenerationException when the chat model returns null response")
    void execute_WhenChatResponseIsNull_ThenThrowsAiGenerationException() {
        // given
        when(chatModelResolver.resolve(PROVIDER)).thenReturn(chatModel);
        when(toolCallbackProvider.getToolCallbacks()).thenReturn(new FunctionToolCallback[0]);

        when(chatModel.call(any(Prompt.class))).thenReturn(null);

        // then
        assertThatThrownBy(() -> chatExecutor.execute(DEFAULT_USER_ID, SYSTEM_TEXT, USER_TEXT, List.of(), null, PROVIDER, MODEL))
                .isInstanceOf(AiGenerationException.class)
                .hasMessageContaining("Received null response from ChatClient");
    }

    private ChatResponse createMockChatResponse(String content, List<AssistantMessage.ToolCall> toolCalls) {
        AssistantMessage assistantMessage = mock(AssistantMessage.class);
        when(assistantMessage.getText()).thenReturn(content);
        if (toolCalls != null && !toolCalls.isEmpty()) {
            when(assistantMessage.getToolCalls()).thenReturn(toolCalls);
        }

        Generation generation = mock(Generation.class);
        when(generation.getOutput()).thenReturn(assistantMessage);

        ChatResponse chatResponse = mock(ChatResponse.class);
        when(chatResponse.getResult()).thenReturn(generation);
        when(chatResponse.getMetadata()).thenReturn(mock(ChatResponseMetadata.class));

        return chatResponse;
    }
}
