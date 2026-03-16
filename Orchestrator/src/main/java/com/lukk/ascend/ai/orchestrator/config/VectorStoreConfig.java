package com.lukk.ascend.ai.orchestrator.config;

import com.lukk.ascend.ai.orchestrator.config.properties.EmbeddingProviderProperties;
import com.lukk.ascend.ai.orchestrator.config.properties.EmbeddingProviderProperties.EmbeddingConfig;
import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
import io.qdrant.client.QdrantClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.MetadataMode;
import org.springframework.ai.openai.OpenAiEmbeddingModel;
import org.springframework.ai.openai.OpenAiEmbeddingOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Configuration
@RequiredArgsConstructor
@EnableConfigurationProperties(EmbeddingProviderProperties.class)
public class VectorStoreConfig {

    private static final String COLLECTION_PREFIX = "ascendai-";

    private final VectorStoreProperties vectorStoreProperties;
    private final QdrantClient qdrantClient;
    private final EmbeddingProviderProperties embeddingProviderProperties;

    @Bean
    public Map<String, QdrantVectorStore> embeddingProviderStoreMap() {
        return embeddingProviderProperties.getProviders().entrySet().stream()
                .collect(Collectors.toMap(
                        Map.Entry::getKey,
                        entry -> buildProviderVectorStore(entry.getKey(), entry.getValue())));
    }

    @Bean
    public QdrantVectorStore vectorStore(Map<String, QdrantVectorStore> embeddingProviderStoreMap) {
        String defaultProvider = embeddingProviderProperties.getDefaultProvider();
        log.info("[VectorStoreConfig] Default VectorStore bean for embedding provider: {}", defaultProvider);
        return embeddingProviderStoreMap.get(defaultProvider);
    }

    private QdrantVectorStore buildProviderVectorStore(String providerName, EmbeddingConfig config) {
        log.info("[VectorStoreConfig] Building EmbeddingModel+VectorStore: provider={}, model={}, dimensions={}",
                providerName, config.getModel(), config.getDimensions());

        OpenAiApi openAiApi = OpenAiApi.builder()
                .baseUrl(config.getBaseUrl())
                .apiKey(config.getApiKey())
                .build();

        OpenAiEmbeddingOptions options = OpenAiEmbeddingOptions.builder()
                .model(config.getModel())
                .dimensions(config.getDimensions())
                .build();

        OpenAiEmbeddingModel embeddingModel = new OpenAiEmbeddingModel(openAiApi, MetadataMode.EMBED, options);

        String collectionName = COLLECTION_PREFIX + config.getDimensions();
        return QdrantVectorStore.builder(qdrantClient, embeddingModel)
                .collectionName(collectionName)
                .build();
    }
}
