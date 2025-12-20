package com.lukk.ascend.ai.orchestrator.test;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.dto.CustomMetadata;
import com.lukk.ascend.ai.orchestrator.dto.PromptRequest;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.metadata.ChatResponseMetadata;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.document.Document;

import java.util.List;
import java.util.Map;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

public class TestDummyBuilder {

    public static final String TEST_PROMPT = "Test Prompt";
    public static final String TEST_USER_ID = "user1";
    public static final String TEST_RESPONSE_CONTENT = "Test Response Content";
    public static final String TEST_TOOL_NAME = "test_tool";

    public static PromptRequest createPromptRequest() {
        return new PromptRequest(TEST_PROMPT);
    }

    public static AiResponse createAiResponse() {
        return new AiResponse(TEST_RESPONSE_CONTENT, createCustomMetadata());
    }

    public static CustomMetadata createCustomMetadata() {
        ChatResponseMetadata metadata = mock(ChatResponseMetadata.class);
        Usage usage = mock(Usage.class);
        // Usage mocking removed to avoid API version mismatch issues.
        // when(metadata.getUsage()).thenReturn(usage); // Optional: keep usage mock if
        // needed, but empty.

        return new CustomMetadata(metadata, List.of(TEST_TOOL_NAME));
    }

    public static ChatResponse createChatResponse() {
        ChatResponse chatResponse = mock(ChatResponse.class);
        Generation generation = mock(Generation.class);
        AssistantMessage message = mock(AssistantMessage.class);
        AssistantMessage.ToolCall toolCall = new AssistantMessage.ToolCall(TEST_TOOL_NAME, "function", TEST_TOOL_NAME,
                "{}");

        when(chatResponse.getResult()).thenReturn(generation);
        when(chatResponse.getResults()).thenReturn(List.of(generation));
        when(chatResponse.getMetadata()).thenReturn(mock(ChatResponseMetadata.class));

        when(generation.getOutput()).thenReturn(message);

        when(message.getText()).thenReturn(TEST_RESPONSE_CONTENT);
        when(message.getToolCalls()).thenReturn(List.of(toolCall));

        return chatResponse;
    }

    public static Document createDocument(String source, String content) {
        return new Document(content, Map.of("source", source, "title", source));
    }
}
