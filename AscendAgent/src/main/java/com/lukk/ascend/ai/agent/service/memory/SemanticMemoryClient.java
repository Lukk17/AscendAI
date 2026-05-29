package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

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
        if (isMissingUserId(userId, "search")) {
            return List.of();
        }
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
                .uri(properties.getBaseUrl() + "/api/v1/memory/search?user_id={userId}&query={query}&limit={limit}&provider={provider}",
                        userId, query, limit, embeddingProvider)
                .retrieve()
                .body(new ParameterizedTypeReference<>() {
                });

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
        if (isMissingUserId(userId, "insertMemory")) {
            return;
        }
        if (!properties.isEnabled()) {
            return;
        }
        log.info("Inserting semantic memory for user: '{}'", userId);
        Map<String, String> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("text", fact);
        body.put("provider", embeddingProvider);

        restClientBuilder.build()
                .post()
                .uri(properties.getBaseUrl() + "/api/v1/memory/insert")
                .body(body)
                .retrieve()
                .toBodilessEntity();
        log.info("Successfully inserted memory fact for user: '{}'", userId);
    }

    // Body is snake_case to match the FastAPI contract on the AscendMemory side.
    public void wipeUserMemory(String userId, String embeddingProvider) {
        if (isMissingUserId(userId, "wipeUserMemory")) {
            return;
        }
        if (!properties.isEnabled()) {
            return;
        }
        log.info("Wiping semantic memory for user: '{}'", userId);
        Map<String, String> body = new HashMap<>();
        body.put("user_id", userId);
        body.put("provider", embeddingProvider);
        try {
            restClientBuilder.build()
                    .post()
                    .uri(properties.getBaseUrl() + "/api/v1/memory/wipe")
                    .body(body)
                    .retrieve()
                    .toBodilessEntity();
            log.info("Successfully wiped semantic memory for user: '{}'", userId);
        } catch (RestClientResponseException e) {
            log.warn("Wipe failed for user '{}'. Status: {}", userId, e.getStatusCode());
        }
    }

    public void deleteMemory(String userId, String memoryId, String embeddingProvider) {
        if (isMissingUserId(userId, "deleteMemory")) {
            return;
        }
        if (!StringUtils.hasText(memoryId)) {
            log.warn("deleteMemory called with blank memoryId for user '{}'; skipping", userId);
            return;
        }
        if (!properties.isEnabled()) {
            return;
        }
        log.info("Deleting semantic memory id '{}' for user: '{}'", memoryId, userId);
        try {
            restClientBuilder.build()
                    .delete()
                    .uri(properties.getBaseUrl() + "/api/v1/memory?memory_id={memoryId}&provider={provider}",
                            memoryId, embeddingProvider)
                    .retrieve()
                    .toBodilessEntity();
            log.info("Successfully deleted memory id '{}' for user: '{}'", memoryId, userId);
        } catch (RestClientResponseException e) {
            log.warn("Delete failed for memory id '{}' (user '{}'). Status: {}", memoryId, userId, e.getStatusCode());
        }
    }

    private boolean isMissingUserId(String userId, String operation) {
        if (StringUtils.hasText(userId)) {
            return false;
        }

        log.warn("SemanticMemoryClient.{} called with blank userId; short-circuiting", operation);

        return true;
    }
}
