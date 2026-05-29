package com.lukk.ascend.ai.agent.memory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryCompactionProperties;
import com.lukk.ascend.ai.agent.config.properties.ChatHistoryProperties;
import com.lukk.ascend.ai.agent.model.ChatHistory;
import com.lukk.ascend.ai.agent.repository.ChatHistoryRepository;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.MessageType;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Objects;

@Component
@Slf4j
public class ChatHistoryCompactionService {

    public static final String SUMMARY_MARKER = "[Conversation summary]";

    private static final Map<String, Integer> CONTEXT_WINDOW_DEFAULTS = Map.of(
            "openai", 128_000,
            "anthropic", 200_000,
            "gemini", 1_000_000,
            "minimax", 200_000,
            "lmstudio", 8_192);

    private static final String SUMMARISER_INSTRUCTION_TEMPLATE = """
            You are compacting an older portion of a chat between a USER and the AscendAI ASSISTANT.
            Produce a single paragraph of at most %d tokens that preserves:
              - Facts the user shared about themselves or their work.
              - Decisions the assistant proposed and the user accepted or rejected.
              - Open threads the user wanted to return to.
            Discard: small talk, restated questions, anything already captured in a prior [Conversation summary] block.
            Do not invent details. If the older portion already begins with "[Conversation summary]", treat it as authoritative and merge.
            Output one paragraph. Begin with the exact literal "[Conversation summary]".
            """;

    private final ChatHistoryCompactionProperties compactionProperties;
    private final ChatHistoryProperties chatHistoryProperties;
    private final ChatHistoryRepository repository;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final ChatModelResolver chatModelResolver;
    private final AiProviderProperties aiProviderProperties;
    private final TransactionTemplate transactionTemplate;

    public ChatHistoryCompactionService(ChatHistoryCompactionProperties compactionProperties,
                                        ChatHistoryProperties chatHistoryProperties,
                                        ChatHistoryRepository repository,
                                        StringRedisTemplate redisTemplate,
                                        ObjectMapper objectMapper,
                                        ChatModelResolver chatModelResolver,
                                        AiProviderProperties aiProviderProperties,
                                        TransactionTemplate transactionTemplate) {
        this.compactionProperties = compactionProperties;
        this.chatHistoryProperties = chatHistoryProperties;
        this.repository = repository;
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
        this.chatModelResolver = chatModelResolver;
        this.aiProviderProperties = aiProviderProperties;
        this.transactionTemplate = transactionTemplate;
    }

    @Async
    public void maybeCompact(String conversationId, String primaryProvider, CompactionOverride override) {
        try {
            doMaybeCompact(conversationId, primaryProvider, override);
        } catch (Exception e) {
            log.warn("[Compaction] failed for conversation '{}': {}", conversationId, e.getMessage());
        }
    }

    private void doMaybeCompact(String conversationId, String primaryProvider, CompactionOverride override) {
        if (!compactionProperties.isEnabled()) {
            return;
        }

        boolean redisOn = chatHistoryProperties.getRedis().isEnabled();
        boolean postgresOn = chatHistoryProperties.getPostgres().isEnabled();
        if (!redisOn && !postgresOn) {
            return;
        }

        List<ChatHistory> history = postgresOn
                ? repository.findAllHistoryOrdered(conversationId)
                : List.of();
        if (history.isEmpty()) {
            return;
        }

        CompactionDecision decision = decideCompaction(history, primaryProvider);
        if (decision.shouldSkip()) {
            return;
        }

        List<ChatHistory> prefix = history.subList(0, decision.prefixCount());
        ResolvedCompactionTarget target = resolveTarget(primaryProvider, override);

        log.info("[Compaction] conversation='{}' turns={} estTokens={} trigger=turn:{}/token:{} prefixCount={} compactionProvider={} compactionModel={}",
                conversationId, history.size(), decision.tokenEstimate(),
                decision.turnTriggered(), decision.tokenTriggered(),
                decision.prefixCount(), target.provider(), target.model());

        String summary = invokeSummariser(target, prefix);
        if (summary == null) {
            return;
        }

        applyToPostgres(conversationId, prefix, summary, postgresOn);
        applyToRedis(conversationId, decision.prefixCount(), summary, redisOn);
    }

    private CompactionDecision decideCompaction(List<ChatHistory> history, String primaryProvider) {
        int turns = history.size();
        int tokenEstimate = estimateTokens(history);
        int contextWindow = contextWindow(primaryProvider);
        boolean turnTriggered = turns >= compactionProperties.getTurnTrigger();
        boolean tokenTriggered = tokenEstimate >= compactionProperties.getTokenTriggerFraction() * contextWindow;
        if (!turnTriggered && !tokenTriggered) {
            return CompactionDecision.noCompaction();
        }

        boolean alreadySummarised = isSummary(history.getFirst());
        if (alreadySummarised && (turns - 1) < compactionProperties.getTurnTrigger()) {
            return CompactionDecision.noCompaction();
        }

        int prefixCount = computePrefixCount(turns);
        if (prefixCount < 1) {
            return CompactionDecision.noCompaction();
        }

        return new CompactionDecision(prefixCount, tokenEstimate, turnTriggered, tokenTriggered);
    }

    private int computePrefixCount(int turns) {
        int prefixCount = Math.max(1, turns - compactionProperties.getKeepRecentTurns());

        return prefixCount >= turns ? turns - 1 : prefixCount;
    }

    private String invokeSummariser(ResolvedCompactionTarget target, List<ChatHistory> prefix) {
        try {
            ChatModel chatModel = chatModelResolver.resolve(target.provider());
            ChatClient.Builder builder = ChatClient.builder(chatModel);
            if (StringUtils.hasText(target.model())) {
                builder.defaultOptions(ChatOptions.builder().model(target.model()).build());
            }
            String instruction = SUMMARISER_INSTRUCTION_TEMPLATE.formatted(compactionProperties.getMaxSummaryTokens());
            String body = renderPrefixForSummariser(prefix);
            String raw = builder.build().prompt()
                    .system(instruction)
                    .user(body)
                    .call()
                    .content();
            return validateSummary(raw);
        } catch (Exception e) {
            log.warn("[Compaction] summariser invocation failed: {}", e.getMessage());
            return null;
        }
    }

    private String validateSummary(String raw) {
        if (raw == null || raw.isBlank()) {
            log.warn("[Compaction] empty summariser output; skipping");
            return null;
        }
        String trimmed = raw.trim();
        if (!trimmed.startsWith(SUMMARY_MARKER)) {
            log.info("[Compaction] summariser output missing marker; auto-prepending");
            trimmed = SUMMARY_MARKER + " " + trimmed;
        }
        int approxTokens = trimmed.length() / 4;
        int hardCap = (int) (compactionProperties.getMaxSummaryTokens() * 1.5);
        if (approxTokens > hardCap) {
            log.warn("[Compaction] summariser output approxTokens={} exceeds hard cap {}; skipping",
                    approxTokens, hardCap);
            return null;
        }
        return trimmed;
    }

    private String renderPrefixForSummariser(List<ChatHistory> prefix) {
        StringBuilder sb = new StringBuilder();
        for (ChatHistory h : prefix) {
            sb.append(h.getRole().toUpperCase()).append(": ").append(h.getContent()).append("\n\n");
        }
        return sb.toString();
    }

    private void applyToPostgres(String conversationId, List<ChatHistory> prefix, String summary, boolean enabled) {
        if (!enabled) {
            return;
        }
        List<Long> idsToDelete = prefix.stream().map(ChatHistory::getId).filter(java.util.Objects::nonNull).toList();
        transactionTemplate.executeWithoutResult(status -> {
            if (!idsToDelete.isEmpty()) {
                repository.deleteAllById(idsToDelete);
            }
            ChatHistory summaryRow = new ChatHistory(
                    null,
                    conversationId,
                    MessageType.SYSTEM.getValue(),
                    summary,
                    LocalDateTime.now());
            repository.save(summaryRow);
        });
    }

    private void applyToRedis(String conversationId, int prefixCount, String summary, boolean enabled) {
        if (!enabled) {
            return;
        }
        String key = "chat:" + conversationId;
        try {
            redisTemplate.opsForList().trim(key, prefixCount, -1);
            String summaryJson = objectMapper.writeValueAsString(
                    new MessageDto(MessageType.SYSTEM.getValue(), summary));
            redisTemplate.opsForList().leftPush(key, summaryJson);
            redisTemplate.expire(key, chatHistoryProperties.getTtl());
        } catch (JsonProcessingException e) {
            log.warn("[Compaction] failed to serialise summary for Redis: {}", e.getMessage());
        }
    }

    private boolean isSummary(ChatHistory entry) {
        return MessageType.SYSTEM.getValue().equalsIgnoreCase(entry.getRole())
                && entry.getContent() != null
                && entry.getContent().startsWith(SUMMARY_MARKER);
    }

    int estimateTokens(List<ChatHistory> history) {
        int total = 0;
        for (ChatHistory h : history) {
            if (h.getContent() != null) {
                total += h.getContent().length() / 4;
            }
        }
        return total;
    }

    int contextWindow(String provider) {
        return CONTEXT_WINDOW_DEFAULTS.getOrDefault(Objects.requireNonNullElse(provider, "lmstudio"), 8_192);
    }

    ResolvedCompactionTarget resolveTarget(String primaryProvider, CompactionOverride override) {
        String provider = override != null && override.hasProvider() ? override.provider() : primaryProvider;
        if (!StringUtils.hasText(provider)) {
            provider = aiProviderProperties.getDefaultProvider();
        }
        String model;
        if (override != null && override.hasModel()) {
            model = override.model();
        } else {
            model = compactionProperties.getProviderDefaults().get(provider);
        }
        return new ResolvedCompactionTarget(provider, model);
    }

    public record ResolvedCompactionTarget(String provider, String model) {
    }

    private record MessageDto(String role, String content) {
    }

    private record CompactionDecision(int prefixCount, int tokenEstimate, boolean turnTriggered,
                                      boolean tokenTriggered) {

        static CompactionDecision noCompaction() {
            return new CompactionDecision(0, 0, false, false);
        }

        boolean shouldSkip() {
            return prefixCount < 1;
        }
    }
}
