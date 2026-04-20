package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.Optional;

@Slf4j
@Service
@RequiredArgsConstructor
public class VectorStoreResolver {

    private final Map<String, QdrantVectorStore> embeddingProviderStoreMap;
    private final EmbeddingProviderProperties embeddingProviderProperties;

    public VectorStore resolve(String embeddingProvider) {
        String resolvedProvider = resolveProviderName(embeddingProvider);
        log.info("[VectorStoreResolver] Resolving VectorStore for embedding provider: {}", resolvedProvider);

        QdrantVectorStore vectorStore = embeddingProviderStoreMap.get(resolvedProvider);
        if (vectorStore == null) {
            log.error("[VectorStoreResolver] Embedding provider '{}' not found. Available: {}",
                    resolvedProvider, embeddingProviderStoreMap.keySet());
            throw new IllegalStateException(
                    "VectorStore for embedding provider '%s' not found".formatted(resolvedProvider));
        }
        return vectorStore;
    }

    public String resolveProviderName(String embeddingProvider) {
        return Optional.ofNullable(embeddingProvider)
                .filter(p -> !p.isBlank())
                .map(String::toLowerCase)
                .orElse(embeddingProviderProperties.getDefaultProvider());
    }
}
