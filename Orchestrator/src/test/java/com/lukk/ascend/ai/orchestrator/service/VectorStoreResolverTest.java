package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.VectorStoreProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class VectorStoreResolverTest {

    @Mock
    private QdrantVectorStore vectorStore768;

    @Mock
    private QdrantVectorStore vectorStore1536;

    @Mock
    private VectorStoreProperties vectorStoreProperties;

    @InjectMocks
    private VectorStoreResolver vectorStoreResolver;

    @Test
    void resolve_WhenLmStudioProvider_ThenReturn768Store() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getProviderCollectionMapping())
                .thenReturn(Map.of("lmstudio", "ascendai-768", "openai", "ascendai-1536"));

        var result = vectorStoreResolver.resolve("lmstudio");

        assertThat(result).isEqualTo(vectorStore768);
    }

    @Test
    void resolve_WhenOpenaiProvider_ThenReturn1536Store() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getProviderCollectionMapping())
                .thenReturn(Map.of("lmstudio", "ascendai-768", "openai", "ascendai-1536"));

        var result = vectorStoreResolver.resolve("openai");

        assertThat(result).isEqualTo(vectorStore1536);
    }

    @Test
    void resolve_WhenNullProvider_ThenReturnDefaultStore() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getDefaultCollection()).thenReturn("ascendai-768");

        var result = vectorStoreResolver.resolve(null);

        assertThat(result).isEqualTo(vectorStore768);
    }

    @Test
    void resolve_WhenBlankProvider_ThenReturnDefaultStore() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getDefaultCollection()).thenReturn("ascendai-768");

        var result = vectorStoreResolver.resolve("  ");

        assertThat(result).isEqualTo(vectorStore768);
    }

    @Test
    void resolve_WhenUnknownProvider_ThenReturnDefaultStore() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getDefaultCollection()).thenReturn("ascendai-768");
        when(vectorStoreProperties.getProviderCollectionMapping())
                .thenReturn(Map.of("lmstudio", "ascendai-768"));

        var result = vectorStoreResolver.resolve("unknownprovider");

        assertThat(result).isEqualTo(vectorStore768);
    }

    @Test
    void resolve_WhenAnthropicProvider_ThenReturn1536Store() {
        Map<String, QdrantVectorStore> storeMap = Map.of(
                "ascendai-768", vectorStore768,
                "ascendai-1536", vectorStore1536);
        setupResolver(storeMap);
        when(vectorStoreProperties.getProviderCollectionMapping())
                .thenReturn(Map.of("anthropic", "ascendai-1536", "lmstudio", "ascendai-768"));

        var result = vectorStoreResolver.resolve("anthropic");

        assertThat(result).isEqualTo(vectorStore1536);
    }

    private void setupResolver(Map<String, QdrantVectorStore> storeMap) {
        org.springframework.test.util.ReflectionTestUtils.setField(vectorStoreResolver, "vectorStoreMap", storeMap);
    }
}
