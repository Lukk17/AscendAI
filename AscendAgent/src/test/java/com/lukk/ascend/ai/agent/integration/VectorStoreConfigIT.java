package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import com.lukk.ascend.ai.agent.service.VectorStoreResolver;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.test.context.TestPropertySource;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Verifies that {@code VectorStoreConfig} wires the right Qdrant collection per
 * embedding provider. Two separate {@code @SpringBootTest} subclasses (not {@code @Nested})
 * because Spring caches one context per property-set and {@code app.embedding.default-provider}
 * has to flip <em>before</em> the {@code @Bean} factories run.
 */
class VectorStoreConfigIT {

    @Tag("integration")
    @TestPropertySource(properties = {
            "app.embedding.default-provider=lmstudio"
    })
    static class WhenLmStudioProviderIT extends TestcontainersBase {

        @org.springframework.test.context.bean.override.mockito.MockitoBean
        org.springframework.ai.mcp.SyncMcpToolCallbackProvider toolCallbackProvider;

        @Autowired
        EmbeddingProviderProperties embeddingProviderProperties;

        @Autowired
        Map<String, QdrantVectorStore> embeddingProviderStoreMap;

        @Autowired
        VectorStore vectorStore;

        @Autowired
        VectorStoreResolver resolver;

        @Test
        void defaultVectorStore_mapsTo_ascendai768() {
            assertThat(embeddingProviderProperties.getDefaultProvider()).isEqualTo("lmstudio");
            assertThat(embeddingProviderProperties.getActiveDimensions()).isEqualTo(768);
            assertThat(embeddingProviderProperties.getActiveCollectionName()).isEqualTo("ascendai-768");

            assertThat(embeddingProviderStoreMap).containsKeys("lmstudio", "openai");
            assertThat(vectorStore).isSameAs(embeddingProviderStoreMap.get("lmstudio"));

            // The resolver must hand back the same default store when no override is given.
            assertThat(resolver.resolve(null)).isSameAs(vectorStore);
            assertThat(resolver.resolve("openai")).isSameAs(embeddingProviderStoreMap.get("openai"));
        }

        @Test
        void perProviderStores_useDistinctCollectionsByDimensions() {
            // The provider→store map must contain entries for every configured provider,
            // each keyed at the dimension-derived collection (ascendai-{dims}).
            assertThat(embeddingProviderStoreMap.get("lmstudio")).isNotNull();
            assertThat(embeddingProviderStoreMap.get("openai")).isNotNull();
            // Different beans for different providers — the Map.toMap factory above must not collapse them.
            assertThat(embeddingProviderStoreMap.get("lmstudio"))
                    .isNotSameAs(embeddingProviderStoreMap.get("openai"));
        }
    }

    @Tag("integration")
    @TestPropertySource(properties = {
            "app.embedding.default-provider=openai"
    })
    static class WhenOpenAiProviderIT extends TestcontainersBase {

        @org.springframework.test.context.bean.override.mockito.MockitoBean
        org.springframework.ai.mcp.SyncMcpToolCallbackProvider toolCallbackProvider;

        @Autowired
        EmbeddingProviderProperties embeddingProviderProperties;

        @Autowired
        Map<String, QdrantVectorStore> embeddingProviderStoreMap;

        @Autowired
        VectorStore vectorStore;

        @Autowired
        VectorStoreResolver resolver;

        @Test
        void defaultVectorStore_mapsTo_ascendai1536() {
            assertThat(embeddingProviderProperties.getDefaultProvider()).isEqualTo("openai");
            assertThat(embeddingProviderProperties.getActiveDimensions()).isEqualTo(1536);
            assertThat(embeddingProviderProperties.getActiveCollectionName()).isEqualTo("ascendai-1536");

            assertThat(embeddingProviderStoreMap).containsKey("openai");
            assertThat(vectorStore).isSameAs(embeddingProviderStoreMap.get("openai"));

            assertThat(resolver.resolve(null)).isSameAs(vectorStore);
            assertThat(resolver.resolveProviderName(null)).isEqualTo("openai");
            assertThat(resolver.resolveProviderName("LMSTUDIO")).isEqualTo("lmstudio");
        }
    }
}
