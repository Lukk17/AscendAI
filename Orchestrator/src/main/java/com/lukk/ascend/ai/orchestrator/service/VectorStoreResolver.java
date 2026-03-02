package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
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

    private final Map<String, QdrantVectorStore> vectorStoreMap;
    private final VectorStoreProperties vectorStoreProperties;

    public VectorStore resolve(String provider) {
        String collectionName = resolveCollectionName(provider);
        log.info("[VectorStoreResolver] Provider: {} -> Collection: {}", provider, collectionName);

        return Optional.ofNullable(vectorStoreMap.get(collectionName))
                .orElseGet(() -> {
                    log.warn("[VectorStoreResolver] Collection '{}' not found in map, falling back to default",
                            collectionName);
                    return vectorStoreMap.get(vectorStoreProperties.getDefaultCollection());
                });
    }

    private String resolveCollectionName(String provider) {
        return Optional.ofNullable(provider)
                .filter(p -> !p.isBlank())
                .map(p -> vectorStoreProperties.getProviderCollectionMapping().getOrDefault(p.toLowerCase(),
                        vectorStoreProperties.getDefaultCollection()))
                .orElse(vectorStoreProperties.getDefaultCollection());
    }
}
