package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.HttpRequest;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.io.IOException;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Service
@RequiredArgsConstructor
@Slf4j
public class SemanticMemoryClient {

    private final RestClient.Builder restClientBuilder;
    private final SemanticMemoryProperties properties;

    public List<SemanticMemoryItem> search(String userId, String query, int limit, String embeddingProvider) {
        return Optional.of(properties)
                .filter(SemanticMemoryProperties::isEnabled)
                .map(props -> executeSearch(userId, query, limit, embeddingProvider))
                .orElseGet(List::of);
    }

    private List<SemanticMemoryItem> executeSearch(String userId, String query, int limit, String embeddingProvider) {
        log.info("Requesting semantic memory from AscendMemory (baseUrl={}) for user: '{}'", properties.getBaseUrl(), userId);
        try {
            return performSearchCall(userId, query, limit, embeddingProvider);
        } catch (Exception e) {
            return handleSearchError(userId, e);
        }
    }

    private List<SemanticMemoryItem> performSearchCall(String userId, String query, int limit, String embeddingProvider) {
        List<SemanticMemoryItem> result = restClientBuilder.build()
                .get()
                .uri(properties.getBaseUrl() + "/api/v1/memory/search?userId={userId}&query={query}&limit={limit}&provider={provider}",
                        userId, query, limit, embeddingProvider)
                .retrieve()
                .body(new ParameterizedTypeReference<>() {});

        List<SemanticMemoryItem> finalResult = Optional.ofNullable(result).orElseGet(List::of);
        log.info("Received {} semantic memory items for user: '{}'", finalResult.size(), userId);
        return finalResult;
    }

    private List<SemanticMemoryItem> handleSearchError(String userId, Exception e) {
        if (e instanceof RestClientResponseException restException) {
            if (restException.getStatusCode().value() == 404) {
                log.debug("No semantic memory found for user '{}' (404 Not Found)", userId);
            } else {
                log.warn("Semantic memory search failed for user '{}'. Status: {}", userId, restException.getStatusCode());
            }
        } else {
            log.warn("Semantic memory search failed for user '{}'. Reason: {}", userId, e.getMessage());
        }
        return List.of();
    }

    public void insertMemory(String userId, String fact, String embeddingProvider) {
        Optional.of(properties)
                .filter(SemanticMemoryProperties::isEnabled)
                .ifPresent(props -> executeInsert(userId, fact, embeddingProvider));
    }

    private void executeInsert(String userId, String fact, String embeddingProvider) {
        log.info("Inserting semantic memory for user: '{}'", userId);
        try {
            performInsertCall(userId, fact, embeddingProvider);
        } catch (Exception e) {
            log.error("Exception while inserting memory for user '{}': {}", userId, e.getMessage());
        }
    }

    private void performInsertCall(String userId, String fact, String embeddingProvider) {
        Map<String, String> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("text", fact);
        body.put("provider", embeddingProvider);

        restClientBuilder.build()
                .post()
                .uri(properties.getBaseUrl() + "/api/v1/memory/insert")
                .body(body)
                .retrieve()
                .onStatus(HttpStatusCode::is4xxClientError, this::handleInsertError)
                .toBodilessEntity();
        log.info("Successfully inserted memory fact for user: '{}'", userId);
    }

    private void handleInsertError(HttpRequest request, ClientHttpResponse response) throws IOException {
        log.warn("Failed to insert memory: HTTP {}", response.getStatusCode());
    }
}