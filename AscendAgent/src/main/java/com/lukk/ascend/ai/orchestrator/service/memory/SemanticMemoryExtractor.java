package com.lukk.ascend.ai.orchestrator.service.memory;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.orchestrator.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.orchestrator.service.ChatModelResolver;
import com.lukk.ascend.ai.orchestrator.service.ChatResponseContentResolver;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
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

            RESPOND WITH ONLY a JSON Array of strings. No explanation, no reasoning, no markdown.
            If there are no facts to save, respond with exactly: []

            Example output:
            ["User loves playing electric guitar", "User's favorite color is red"]
            """;

    private final ChatModelResolver chatModelResolver;
    private final AiProviderProperties aiProviderProperties;
    private final SemanticMemoryClient memoryClient;
    private final ObjectMapper objectMapper;
    private final ChatResponseContentResolver chatResponseContentResolver;

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

        ChatClient.Builder clientBuilder = ChatClient.builder(chatModel)
                .defaultSystem(EXTRACTOR_INSTRUCTION);

        Optional.ofNullable(extractionModel)
                .filter(StringUtils::hasText)
                .ifPresent(m -> clientBuilder.defaultOptions(ChatOptions.builder().model(m).build()));

        ChatClient chatClient = clientBuilder.build();

        ChatResponse chatResponse = chatClient.prompt()
                .user(userText)
                .call()
                .chatResponse();

        String responseContent = chatResponseContentResolver.resolveContent(chatResponse);

        List<String> facts = extractFactsFromJson(responseContent);
        facts.forEach(fact -> memoryClient.insertMemory(userId, fact, embeddingProvider));
    }

    private void handleExtractionError(String userId, Exception e) {
        log.warn("Failed to extract or insert semantic memory asynchronously for user '{}'. Reason: {}", userId, e.getMessage());
    }

    /**
     * Resolves which model to use for extraction.
     * Priority: user's requested model > provider's configured memoryExtractionModel > null (provider default).
     */
    private String resolveExtractionModel(String provider, String requestedModel) {
        if (StringUtils.hasText(requestedModel)) {
            return requestedModel;
        }
        return Optional.ofNullable(aiProviderProperties.getProviders().get(provider))
                .map(AiProviderProperties.ProviderConfig::getMemoryExtractionModel)
                .orElse(null);
    }

    private List<String> extractFactsFromJson(String jsonString) {
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
            return objectMapper.readValue(cleanedJson, new TypeReference<List<String>>() {});
        } catch (JsonProcessingException e) {
            return extractEmbeddedJsonArray(cleanedJson);
        }
    }

    private List<String> extractEmbeddedJsonArray(String text) {
        int lastOpen = text.lastIndexOf('[');
        int lastClose = text.lastIndexOf(']');
        if (lastOpen >= 0 && lastClose > lastOpen) {
            String candidate = text.substring(lastOpen, lastClose + 1);
            try {
                return objectMapper.readValue(candidate, new TypeReference<List<String>>() {});
            } catch (JsonProcessingException ex) {
                // Fall through to warn
            }
        }
        log.warn("Could not parse memory extraction response as JSON Array. Content: {}", text);
        return List.of();
    }
}