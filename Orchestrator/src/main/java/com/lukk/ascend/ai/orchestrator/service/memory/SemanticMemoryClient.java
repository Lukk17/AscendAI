package com.lukk.ascend.ai.orchestrator.service.memory;

import com.lukk.ascend.ai.orchestrator.config.properties.SemanticMemoryProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.List;

@Service
@RequiredArgsConstructor
public class SemanticMemoryClient {

    private final RestClient.Builder restClientBuilder;
    private final SemanticMemoryProperties properties;

    public List<SemanticMemoryItem> search(String userId, String query, int limit) {
        if (!properties.isEnabled()) {
            return List.of();
        }

        return restClientBuilder.build()
                .get()
                .uri(properties.getBaseUrl() + "/api/memory/search?userId={userId}&query={query}&limit={limit}", userId, query, limit)
                .retrieve()
                .body(new ParameterizedTypeReference<>() {
                });
    }
}
