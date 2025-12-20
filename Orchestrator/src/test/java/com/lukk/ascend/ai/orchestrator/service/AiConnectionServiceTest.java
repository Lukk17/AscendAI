package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.exception.AiGenerationException;
import com.lukk.ascend.ai.orchestrator.test.TestDummyBuilder;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentMatchers;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.client.advisor.api.Advisor;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.anyMap;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AiConnectionServiceTest {

    @Mock
    private ChatClient chatClient;

    @Mock
    private VectorStore vectorStore;

    @Mock
    private ChatClient.ChatClientRequestSpec requestSpec;

    @Mock
    private ChatClient.CallResponseSpec callResponseSpec;

    @InjectMocks
    private AiConnectionService aiConnectionService;

    @Test
    void prompt_ShouldReturnAiResponse_WhenCallIsSuccessful() {
        // given
        String userPrompt = TestDummyBuilder.TEST_PROMPT;
        String userId = TestDummyBuilder.TEST_USER_ID;
        ChatResponse mockResponse = TestDummyBuilder.createChatResponse();

        mockChatClientPromptChain();
        when(callResponseSpec.chatResponse()).thenReturn(mockResponse);

        // when
        AiResponse result = aiConnectionService.prompt(userPrompt, userId);

        // then
        assertNotNull(result);
        assertEquals(TestDummyBuilder.TEST_RESPONSE_CONTENT, result.content());
        assertTrue(result.metadata().getToolsUsed().contains(TestDummyBuilder.TEST_TOOL_NAME));
    }

    @Test
    void prompt_ShouldThrowException_WhenResponseIsNull() {
        // given
        String userPrompt = TestDummyBuilder.TEST_PROMPT;
        String userId = TestDummyBuilder.TEST_USER_ID;

        mockChatClientPromptChain();
        when(callResponseSpec.chatResponse()).thenReturn(null);

        // when & then
        assertThrows(AiGenerationException.class, () -> aiConnectionService.prompt(userPrompt, userId));
    }

    private void mockChatClientPromptChain() {
        when(chatClient.prompt()).thenReturn(requestSpec);
        when(requestSpec.user(anyString())).thenReturn(requestSpec);
        when(requestSpec.advisors(ArgumentMatchers.<Consumer<ChatClient.AdvisorSpec>>any()))
                .thenReturn(requestSpec);
        when(requestSpec.advisors(any(Advisor.class)))
                .thenReturn(requestSpec);
        when(requestSpec.toolContext(anyMap())).thenReturn(requestSpec);
        when(requestSpec.call()).thenReturn(callResponseSpec);
    }
}
