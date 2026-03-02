package com.lukk.ascend.ai.orchestrator.config;

import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
import io.qdrant.client.QdrantClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Configuration
@RequiredArgsConstructor
public class VectorStoreConfig {

    private final VectorStoreProperties vectorStoreProperties;
    private final QdrantClient qdrantClient;
    private final EmbeddingModel embeddingModel;

    @Bean
    @Primary
    public Map<String, QdrantVectorStore> vectorStoreMap() {
        return vectorStoreProperties.getCollections().stream()
                .collect(Collectors.toMap(
                        VectorStoreProperties.CollectionConfig::getName,
                        this::buildVectorStore));
    }

    @Bean
    public QdrantVectorStore vectorStore() {
        String defaultCollection = vectorStoreProperties.getDefaultCollection();
        log.info("[VectorStoreConfig] Creating default VectorStore bean for collection: {}", defaultCollection);
        return vectorStoreMap().get(defaultCollection);
    }

    private QdrantVectorStore buildVectorStore(VectorStoreProperties.CollectionConfig config) {
        log.info("[VectorStoreConfig] Building VectorStore for collection: {} (size: {})", config.getName(),
                config.getSize());
        return QdrantVectorStore.builder(qdrantClient, embeddingModel)
                .collectionName(config.getName())
                .build();
    }
}
