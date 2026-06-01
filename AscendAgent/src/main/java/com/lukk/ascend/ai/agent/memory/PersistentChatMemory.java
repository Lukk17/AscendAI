package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.exception.ServiceException;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import jakarta.annotation.PostConstruct;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.MessageType;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.lang.NonNull;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Component
@Slf4j
public class PersistentChatMemory implements ChatMemory {

    private final ChatHistoryRepository repository;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final ChatHistoryProperties chatHistoryProperties;
    private final ChatHistoryCompactionProperties compactionProperties;
    private final ChatHistoryCompactionService compactionService;

    public PersistentChatMemory(ChatHistoryRepository repository,
                                StringRedisTemplate redisTemplate,
                                ObjectMapper objectMapper,
                                ChatHistoryProperties chatHistoryProperties,
                                ChatHistoryCompactionProperties compactionProperties,
                                ChatHistoryCompactionService compactionService) {
        this.repository = repository;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.chatHistoryProperties = chatHistoryProperties;
        this.compactionProperties = compactionProperties;
        this.compactionService = compactionService;
    }

    @PostConstruct
    void logToggleState() {
        log.info("[PersistentChatMemory] Chat history backends - Redis: [{}], Postgres: [{}]; Compaction: [{}]",
                chatHistoryProperties.getRedis().isEnabled() ? "Enabled" : "Disabled",
                chatHistoryProperties.getPostgres().isEnabled() ? "Enabled" : "Disabled",
                compactionProperties.isEnabled() ? "Enabled" : "Disabled");
    }

    public List<Message> get(String conversationId, int lastN) {
        boolean redisEnabled = chatHistoryProperties.getRedis().isEnabled();
        boolean postgresEnabled = chatHistoryProperties.getPostgres().isEnabled();
        if (!redisEnabled && !postgresEnabled) {
            return Collections.emptyList();
        }

        String key = "chat:" + conversationId;
        try {
            if (redisEnabled) {
                List<Message> cached = loadFromRedis(key);
                if (!cached.isEmpty()) {
                    List<Message> result = sliceTail(cached, lastN);

                    log.info("Retrieved History | Size: {} | Source: REDIS", result.size());

                    return result;
                }
            }

            if (!postgresEnabled) {
                return Collections.emptyList();
            }

            List<Message> hydrated = loadFromPostgres(conversationId);
            if (redisEnabled && !hydrated.isEmpty()) {
                populateRedisCache(key, hydrated);
            }

            List<Message> result = sliceTail(hydrated, lastN);

            log.info("Retrieved History | Size: {} | Source: Postgres", result.size());

            return result;

        } catch (Exception e) {
            log.error("Failed to get messages from memory for conversation: {}", conversationId, e);

            throw new ServiceException("Failed to retrieve chat memory", e);
        }
    }

    @Override
    @NonNull
    public List<Message> get(@NonNull String conversationId) {
        return get(conversationId, effectiveCacheSize());
    }

    private List<Message> loadFromRedis(String key) throws JsonProcessingException {
        List<String> cachedJson = redisTemplate.opsForList().range(key, 0, -1);
        if (cachedJson == null || cachedJson.isEmpty()) {
            return List.of();
        }

        List<Message> messages = new ArrayList<>(cachedJson.size());
        for (String json : cachedJson) {
            MessageDto dto = objectMapper.readValue(json, MessageDto.class);
            messages.add(mapDtoToMessage(dto));
        }

        return messages;
    }

    private List<Message> loadFromPostgres(String conversationId) {
        List<ChatHistory> history = repository.findRecentHistory(conversationId, effectiveCacheSize());
        List<Message> hydrated = history.stream()
                .map(this::mapToMessage)
                .collect(Collectors.toList());
        Collections.reverse(hydrated);

        return hydrated;
    }

    private void populateRedisCache(String key, List<Message> hydrated) throws JsonProcessingException {
        List<String> jsonMessages = new ArrayList<>(hydrated.size());
        for (Message msg : hydrated) {
            jsonMessages.add(objectMapper
                    .writeValueAsString(new MessageDto(msg.getMessageType().getValue(), msg.getText())));
        }

        redisTemplate.opsForList().rightPushAll(key, jsonMessages);
        redisTemplate.expire(key, chatHistoryProperties.getTtl());
    }

    private static List<Message> sliceTail(List<Message> messages, int lastN) {
        int start = Math.max(0, messages.size() - lastN);

        return messages.subList(start, messages.size());
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
    public void add(@NonNull String conversationId, @NonNull List<Message> messages) {
        add(conversationId, messages, null, CompactionOverride.EMPTY);
    }

    public void add(String conversationId, List<Message> messages, String primaryProvider, CompactionOverride override) {
        boolean redisEnabled = chatHistoryProperties.getRedis().isEnabled();
        boolean postgresEnabled = chatHistoryProperties.getPostgres().isEnabled();
        if (!redisEnabled && !postgresEnabled) {
            return;
        }

        String key = "chat:" + conversationId;
        try {
            for (Message message : messages) {
                if (redisEnabled) {
                    String json = objectMapper
                            .writeValueAsString(new MessageDto(message.getMessageType().getValue(), message.getText()));
                    redisTemplate.opsForList().rightPush(key, json);
                }
                if (postgresEnabled) {
                    persistToDb(conversationId, message);
                }
            }
            if (redisEnabled) {
                redisTemplate.opsForList().trim(key, 0, effectiveCacheSize() - 1);
                redisTemplate.expire(key, chatHistoryProperties.getTtl());
            }
        } catch (Exception e) {
            log.error("Failed to add messages to memory for conversation: {}", conversationId, e);
            throw new ServiceException("Failed to add to chat memory", e);
        }

        try {
            compactionService.maybeCompact(conversationId, primaryProvider, override);
        } catch (Exception e) {
            log.warn("Compaction dispatch threw for conversation '{}': {}", conversationId, e.getMessage());
        }
    }

    /**
     * When compaction is enabled the Redis cap must accommodate the post-compaction
     * shape of {@code 1 summary + keepRecentTurns} entries. Otherwise, the regular
     * trim would drop the freshly written summary on the next user turn.
     */
    private int effectiveCacheSize() {
        int base = chatHistoryProperties.getMaxSize();
        if (!compactionProperties.isEnabled()) {
            return base;
        }
        return Math.max(base, compactionProperties.getKeepRecentTurns() + 1);
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
    public void clear(@NonNull String conversationId) {
        String key = "chat:" + conversationId;

        redisTemplate.delete(key);
    }

    private record MessageDto(String role, String content) {
    }
}
