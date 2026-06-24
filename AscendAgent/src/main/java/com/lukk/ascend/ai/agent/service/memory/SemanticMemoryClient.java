package com.lukk.ascend.ai.agent.service.memory;

import com.lukk.ascend.ai.agent.config.properties.SemanticMemoryProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.TimeoutException;

@Service
@Slf4j
public class SemanticMemoryClient {

    private static final String METRIC_INSERT_FAILED = "memory.insert.failed";
    private static final String METRIC_SEARCH_DURATION = "memory.search.duration";
    private static final String OUTCOME_OK = "ok";
    private static final String OUTCOME_ERROR = "error";

    private final RestClient.Builder restClientBuilder;
    private final SemanticMemoryProperties properties;
    private final MeterRegistry meterRegistry;

    public SemanticMemoryClient(RestClient.Builder restClientBuilder,
                                SemanticMemoryProperties properties,
                                MeterRegistry meterRegistry) {
        this.restClientBuilder = restClientBuilder;
        this.properties = properties;
        this.meterRegistry = meterRegistry;
    }

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
        Timer.Sample sample = Timer.start(meterRegistry);
        String outcome = OUTCOME_OK;
        try {
            List<SemanticMemoryItem> result = performSearchCall(userId, query, limit, embeddingProvider);
            return result;
        } catch (Exception e) {
            outcome = OUTCOME_ERROR;
            return handleSearchError(userId, e);
        } finally {
            sample.stop(Timer.builder(METRIC_SEARCH_DURATION)
                    .tag("embedding_provider", embeddingProvider != null ? embeddingProvider : "unknown")
                    .tag("outcome", outcome)
                    .register(meterRegistry));
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

        try {
            restClientBuilder.build()
                    .post()
                    .uri(properties.getBaseUrl() + "/api/v1/memory/insert")
                    .body(body)
                    .retrieve()
                    .toBodilessEntity();
            log.info("Successfully inserted memory fact for user: '{}'", userId);
        } catch (Exception e) {
            String reason = classifyInsertFailure(e);
            Counter.builder(METRIC_INSERT_FAILED)
                    .tag("embedding_provider", embeddingProvider != null ? embeddingProvider : "unknown")
                    .tag("reason", reason)
                    .register(meterRegistry)
                    .increment();
            throw e;
        }
    }

    private static String classifyInsertFailure(Exception e) {
        if (e instanceof RestClientResponseException rce) {
            int status = rce.getStatusCode().value();
            if (status >= 400 && status < 500) {
                return "4xx";
            }
            if (status >= 500) {
                return "5xx";
            }
        }
        if (e instanceof ResourceAccessException rae) {
            Throwable cause = rae.getCause();
            if (cause instanceof TimeoutException) {
                return "timeout";
            }
            return "connect_error";
        }
        return "error";
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
