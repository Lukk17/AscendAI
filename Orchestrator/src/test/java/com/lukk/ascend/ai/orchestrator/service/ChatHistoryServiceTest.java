package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.memory.PersistentChatMemory;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Captor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatHistoryServiceTest {

    private static final String DEFAULT_USER_ID = "user1";

    @Mock
    private PersistentChatMemory persistentChatMemory;

    @InjectMocks
    private ChatHistoryService chatHistoryService;

    @Captor
    private ArgumentCaptor<List<Message>> messageListCaptor;

    @Test
    void loadHistory_WhenInvoked_ThenReturnsHistoryFromMemory() {
        // given
        List<Message> expectedHistory = List.of(new UserMessage("Hi"), new AssistantMessage("Hello"));
        when(persistentChatMemory.get(DEFAULT_USER_ID, 100)).thenReturn(expectedHistory);

        // when
        List<Message> result = chatHistoryService.loadHistory(DEFAULT_USER_ID);

        // then
        assertThat(result).hasSize(2).isEqualTo(expectedHistory);
        verify(persistentChatMemory).get(DEFAULT_USER_ID, 100);
    }

    @Test
    void loadHistory_WhenNoHistoryExists_ThenReturnsEmptyList() {
        // given
        when(persistentChatMemory.get(DEFAULT_USER_ID, 100)).thenReturn(List.of());

        // when
        List<Message> result = chatHistoryService.loadHistory(DEFAULT_USER_ID);

        // then
        assertThat(result).isEmpty();
        verify(persistentChatMemory).get(DEFAULT_USER_ID, 100);
    }

    @Test
    void saveHistory_WhenInvoked_ThenWrapsAndSavesMessages() {
        // given
        String userPrompt = "What is the weather?";
        String responseContent = "It is sunny.";

        // when
        chatHistoryService.saveHistory(DEFAULT_USER_ID, userPrompt, responseContent);

        // then
        verify(persistentChatMemory).add(eq(DEFAULT_USER_ID), messageListCaptor.capture());
        
        List<Message> capturedMessages = messageListCaptor.getValue();
        assertThat(capturedMessages).hasSize(2);
        
        Message capturedUserMsg = capturedMessages.get(0);
        assertThat(capturedUserMsg).isInstanceOf(UserMessage.class);
        assertThat(capturedUserMsg.getText()).isEqualTo(userPrompt);

        Message capturedAssistantMsg = capturedMessages.get(1);
        assertThat(capturedAssistantMsg).isInstanceOf(AssistantMessage.class);
        assertThat(capturedAssistantMsg.getText()).isEqualTo(responseContent);
    }
}
