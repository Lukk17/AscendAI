package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.memory.PersistentChatMemory;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
public class ChatHistoryService {

    private final PersistentChatMemory persistentChatMemory;

    public List<Message> loadHistory(String userId) {
        List<Message> history = persistentChatMemory.get(userId, 100);
        log.info("Loaded chat history for user: {}, size: {}", userId, history.size());
        return history;
    }

    public void saveHistory(String userId, String userPrompt, String responseContent) {
        log.info("Saving chat history for User: {}", userId);
        Message userMsg = new UserMessage(userPrompt);
        Message assistantMsg = new AssistantMessage(responseContent);
        persistentChatMemory.add(userId, List.of(userMsg, assistantMsg));
    }
}
