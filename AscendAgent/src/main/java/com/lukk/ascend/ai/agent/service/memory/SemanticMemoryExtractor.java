package com.lukk.ascend.ai.agent.service.memory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.service.ChatModelResolver;
import com.lukk.ascend.ai.agent.service.ChatResponseContentResolver;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategy;
import com.lukk.ascend.ai.agent.service.cache.PromptCacheStrategyResolver;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.ChatOptions;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class SemanticMemoryExtractor {

    private static final String EXTRACTOR_INSTRUCTION = """
            Identify exclusively standalone semantic facts (identity, strict preference, name, contact) from the attached user prompt.
            Disregard general knowledge or questions.
            
            Output ONLY a JSON array of strings. No prose, no markdown fences, no chain-of-thought, no explanation.
            If there are no facts to save, output exactly: []
            
            Example output:
            ["User loves playing electric guitar", "User's favorite color is red"]
            """;

    private final ChatModelResolver chatModelResolver;
    private final AiProviderProperties aiProviderProperties;
    private final SemanticMemoryClient memoryClient;
    private final ObjectMapper objectMapper;
    private final ChatResponseContentResolver chatResponseContentResolver;
    private final PromptCacheStrategyResolver cacheStrategyResolver;

    public void extract(String userId, String userText, String provider, String model, String embeddingProvider) {
        Thread.startVirtualThread(() -> processExtraction(userId, userText, provider, model, embeddingProvider));
    }

    private void processExtraction(String userId, String userText, String provider, String model, String embeddingProvider) {
        log.debug("Initiating asynchronous semantic memory extraction for user '{}' via provider '{}'", userId, provider);
        try {
            executeExtractionFlow(userId, userText, provider, model, embeddingProvider);
        } catch (Exception e) {
            handleExtractionError(userId, e);
        }
    }

    private void executeExtractionFlow(String userId, String userText, String provider, String model, String embeddingProvider) {
        String extractionModel = resolveExtractionModel(provider, model);
        ChatModel chatModel = chatModelResolver.resolve(provider);
        PromptCacheStrategy strategy = cacheStrategyResolver.resolve(provider);
        ChatOptions decoratedOptions = strategy.buildOptions(extractionModel);

        ChatResponse chatResponse;
        try {
            chatResponse = invokeExtractor(chatModel, userText, extractionModel, decoratedOptions);
        } catch (RuntimeException e) {
            if (!strategy.isCacheConfigError(e)) {
                throw e;
            }
            log.warn("[PromptCache] provider={} extractor cache call failed, retrying without cache: {}",
                    strategy.providerName(), e.getMessage());
            ChatOptions fallback = StringUtils.hasText(extractionModel)
                    ? ChatOptions.builder().model(extractionModel).build() : null;
            chatResponse = invokeExtractor(chatModel, userText, extractionModel, fallback);
        }

        strategy.recordOutcome(userId, chatResponse);

        String responseContent = chatResponseContentResolver.resolveContent(chatResponse);

        List<String> facts = extractFactsFromJson(responseContent);
        insertFactsWithTally(userId, facts, embeddingProvider);
    }

    private ChatResponse invokeExtractor(ChatModel chatModel, String userText, String extractionModel, ChatOptions options) {
        ChatClient.Builder clientBuilder = ChatClient.builder(chatModel);
        if (options == null && StringUtils.hasText(extractionModel)) {
            clientBuilder.defaultOptions(ChatOptions.builder().model(extractionModel).build());
        }
        ChatClient chatClient = clientBuilder.build();

        List<Message> messages = List.of(new SystemMessage(EXTRACTOR_INSTRUCTION));
        var spec = chatClient.prompt().messages(messages).user(userText);
        if (options != null) {
            spec = spec.options(options);
        }
        return spec.call().chatResponse();
    }

    private void insertFactsWithTally(String userId, List<String> facts, String embeddingProvider) {
        if (facts.isEmpty()) {
            return;
        }
        int ok = 0;
        int failed = 0;
        for (String fact : facts) {
            try {
                memoryClient.insertMemory(userId, fact, embeddingProvider);
                ok++;
            } catch (Exception e) {
                failed++;
                log.debug("Insert failed for fact '{}' (user '{}'): {}", fact, userId, e.getMessage());
            }
        }
        if (failed > 0) {
            log.warn("Inserted {}/{} facts for user '{}' (failed: {})", ok, facts.size(), userId, failed);
        }
    }

    private void handleExtractionError(String userId, Exception e) {
        log.warn("Failed to extract or insert semantic memory asynchronously for user '{}'. Reason: {}", userId, e.getMessage());
    }

    private String resolveExtractionModel(String provider, String requestedModel) {
        if (StringUtils.hasText(requestedModel)) {
            return requestedModel;
        }
        return Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
                .map(AiProviderProperties.ProviderConfig::getMemoryExtractionModel)
                .orElse(null);
    }

    List<String> extractFactsFromJson(String jsonString) {
        return Optional.ofNullable(jsonString)
                .filter(StringUtils::hasText)
                .map(String::trim)
                .map(this::removeMarkdownCodeBlocks)
                .map(this::parseJsonArray)
                .orElseGet(List::of);
    }

    private String removeMarkdownCodeBlocks(String json) {
        return Optional.of(json)
                .map(j -> j.startsWith("```json") ? j.replace("```json", "") : j)
                .map(j -> j.endsWith("```") ? j.substring(0, j.lastIndexOf("```")) : j)
                .map(String::trim)
                .orElse(json);
    }

    private List<String> parseJsonArray(String cleanedJson) {
        try {
            return objectMapper.readValue(cleanedJson, new TypeReference<List<String>>() {
            });
        } catch (JsonProcessingException e) {
            return extractEmbeddedJsonArray(cleanedJson);
        }
    }

    /**
     * Falls back to a balanced-bracket scan when the response isn't pure JSON.
     * Thinking models (MiniMax-M2.x, etc.) prepend chain-of-thought before the array, sometimes
     * append commentary, sometimes wrap in inline code. We scan from the end of the string for
     * the last balanced {@code [...]} substring (string-aware, depth-counted) and try to parse it.
     * Returns an empty list and logs WARN once if all attempts fail. Never throws.
     */
    private List<String> extractEmbeddedJsonArray(String text) {
        Optional<String> candidate = findLastBalancedJsonArray(text);
        if (candidate.isPresent()) {
            try {
                return objectMapper.readValue(candidate.get(), new TypeReference<List<String>>() {
                });
            } catch (JsonProcessingException ex) {
                log.debug("Embedded JSON array candidate parse failed: {}", ex.getMessage());
            }
        }
        log.warn("Could not parse memory extraction response as JSON Array. Content: {}", text);
        return List.of();
    }

    /**
     * Single forward pass collecting every top-level {@code [...]} range, returns the last one.
     * String-aware (ignores brackets inside JSON strings) and escape-aware (handles {@code \"}).
     */
    private Optional<String> findLastBalancedJsonArray(String text) {
        if (text == null || text.isBlank()) {
            return Optional.empty();
        }

        BracketScanState state = new BracketScanState();
        for (int i = 0; i < text.length(); i++) {
            state.consume(text.charAt(i), i);
        }

        return state.lastRange().map(range -> text.substring(range.start(), range.end() + 1));
    }

    private record BracketRange(int start, int end) {
    }

    private static final class BracketScanState {

        private int depth = 0;
        private int currentStart = -1;
        private BracketRange lastClosed;
        private boolean inString = false;
        private boolean escaped = false;

        void consume(char c, int index) {
            if (escaped) {
                escaped = false;
                return;
            }
            if (c == '\\') {
                escaped = true;
                return;
            }
            if (c == '"') {
                inString = !inString;
                return;
            }
            if (inString) {
                return;
            }

            if (c == '[') {
                if (depth == 0) {
                    currentStart = index;
                }
                depth++;
                return;
            }
            if (c == ']' && depth > 0) {
                depth--;
                if (depth == 0 && currentStart >= 0) {
                    lastClosed = new BracketRange(currentStart, index);
                    currentStart = -1;
                }
            }
        }

        Optional<BracketRange> lastRange() {
            return Optional.ofNullable(lastClosed);
        }
    }
}
