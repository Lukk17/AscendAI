package com.lukk.ascend.ai.orchestrator.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.exception.ServiceException;
import com.lukk.ascend.ai.orchestrator.model.ChatHistory;
import com.lukk.ascend.ai.orchestrator.repository.ChatHistoryRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.messages.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Component
@RequiredArgsConstructor
@Slf4j
public class PersistentChatMemory implements ChatMemory {

    private final ChatHistoryRepository repository;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    @Value("${app.memory.chat-history.max-size}")
    private int maxSize;

    public List<Message> get(String conversationId, int lastN) {
        String key = "chat:" + conversationId;
        try {
            List<String> cachedJson = redisTemplate.opsForList().range(key, 0, -1);
            if (cachedJson != null && !cachedJson.isEmpty()) {
                List<Message> cachedMessages = new ArrayList<>();
                for (String json : cachedJson) {
                    MessageDto dto = objectMapper.readValue(json, MessageDto.class);
                    cachedMessages.add(mapDtoToMessage(dto));
                }

                int start = Math.max(0, cachedMessages.size() - lastN);
                List<Message> result = cachedMessages.subList(start, cachedMessages.size());
                log.info("Retrieved History | Size: {} | Source: REDIS", result.size());
                return result;
            }

            List<ChatHistory> history = repository.findRecentHistory(conversationId, maxSize);

            List<Message> hydrated = history.stream()
                    .map(this::mapToMessage)
                    .collect(Collectors.toList());
            Collections.reverse(hydrated);

            if (!hydrated.isEmpty()) {
                List<String> jsonMessages = new ArrayList<>();
                for (Message msg : hydrated) {
                    jsonMessages.add(objectMapper
                            .writeValueAsString(new MessageDto(msg.getMessageType().getValue(), msg.getText())));
                }
                redisTemplate.opsForList().rightPushAll(key, jsonMessages);
            }

            int start = Math.max(0, hydrated.size() - lastN);
            List<Message> result = hydrated.subList(start, hydrated.size());
            log.info("Retrieved History | Size: {} | Source: Postgres", result.size());
            return result;

        } catch (Exception e) {
            log.error("Failed to get messages from memory for conversation: {}", conversationId, e);
            throw new ServiceException("Failed to retrieve chat memory", e);
        }
    }

    @Override
    public List<Message> get(String conversationId) {
        return get(conversationId, maxSize);
    }

    private Message mapToMessage(ChatHistory h) {
        return createMessage(h.getRole(), h.getContent());
    }

    private Message mapDtoToMessage(MessageDto dto) {
        return createMessage(dto.role(), dto.content());
    }

    private Message createMessage(String role, String content) {
        if (MessageType.USER.getValue().equalsIgnoreCase(role)) {
            return new UserMessage(content);
        } else if (MessageType.ASSISTANT.getValue().equalsIgnoreCase(role)) {
            return new AssistantMessage(content);
        } else if (MessageType.SYSTEM.getValue().equalsIgnoreCase(role)) {
            return new SystemMessage(content);
        }
        return new UserMessage(content);
    }

    @Override
    public void add(String conversationId, List<Message> messages) {
        String key = "chat:" + conversationId;
        try {
            for (Message message : messages) {
                String json = objectMapper
                        .writeValueAsString(new MessageDto(message.getMessageType().getValue(), message.getText()));
                redisTemplate.opsForList().rightPush(key, json);

                persistToDb(conversationId, message);
            }
            redisTemplate.opsForList().trim(key, 0, maxSize - 1);
        } catch (Exception e) {
            log.error("Failed to add messages to memory for conversation: {}", conversationId, e);
            throw new ServiceException("Failed to add to chat memory", e);
        }
    }

    @Async
    public void persistToDb(String userId, Message message) {
        try {
            ChatHistory entity = new ChatHistory(
                    null,
                    userId,
                    message.getMessageType().getValue(),
                    message.getText(),
                    LocalDateTime.now());
            repository.save(entity);
        } catch (Exception e) {
            log.error("Async DB persist failed for user: {}", userId, e);
        }
    }

    @Override
    public void clear(String conversationId) {
        String key = "chat:" + conversationId;
        redisTemplate.delete(key);
    }

    private record MessageDto(String role, String content) {
    }
}
