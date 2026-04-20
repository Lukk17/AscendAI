package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.vectorstore.qdrant.QdrantVectorStore;

import org.springframework.test.util.ReflectionTestUtils;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class VectorStoreResolverTest {

    private static final String PROVIDER_LMSTUDIO = "lmstudio";
    private static final String PROVIDER_OPENAI = "openai";

    @Mock
    private QdrantVectorStore vectorStoreLmstudio;

    @Mock
    private QdrantVectorStore vectorStoreOpenai;

    @Mock
    private EmbeddingProviderProperties embeddingProviderProperties;

    @InjectMocks
    private VectorStoreResolver vectorStoreResolver;

    @Test
    void resolve_WhenExplicitLmstudio_ThenReturnLmstudioStore() {
        // given
        setupResolver(Map.of(PROVIDER_LMSTUDIO, vectorStoreLmstudio, PROVIDER_OPENAI, vectorStoreOpenai));

        // when
        var result = vectorStoreResolver.resolve(PROVIDER_LMSTUDIO);

        // then
        assertThat(result).isEqualTo(vectorStoreLmstudio);
    }

    @Test
    void resolve_WhenExplicitOpenai_ThenReturnOpenaiStore() {
        // given
        setupResolver(Map.of(PROVIDER_LMSTUDIO, vectorStoreLmstudio, PROVIDER_OPENAI, vectorStoreOpenai));

        // when
        var result = vectorStoreResolver.resolve(PROVIDER_OPENAI);

        // then
        assertThat(result).isEqualTo(vectorStoreOpenai);
    }

    @Test
    void resolve_WhenNullProvider_ThenReturnDefaultStore() {
        // given
        setupResolver(Map.of(PROVIDER_LMSTUDIO, vectorStoreLmstudio, PROVIDER_OPENAI, vectorStoreOpenai));
        when(embeddingProviderProperties.getDefaultProvider()).thenReturn(PROVIDER_LMSTUDIO);

        // when
        var result = vectorStoreResolver.resolve(null);

        // then
        assertThat(result).isEqualTo(vectorStoreLmstudio);
    }

    @Test
    void resolve_WhenBlankProvider_ThenReturnDefaultStore() {
        // given
        setupResolver(Map.of(PROVIDER_LMSTUDIO, vectorStoreLmstudio, PROVIDER_OPENAI, vectorStoreOpenai));
        when(embeddingProviderProperties.getDefaultProvider()).thenReturn(PROVIDER_LMSTUDIO);

        // when
        var result = vectorStoreResolver.resolve("  ");

        // then
        assertThat(result).isEqualTo(vectorStoreLmstudio);
    }

    @Test
    void resolve_WhenUnknownProvider_ThenThrowIllegalStateException() {
        // given
        setupResolver(Map.of(PROVIDER_LMSTUDIO, vectorStoreLmstudio));

        // then
        assertThatThrownBy(() -> vectorStoreResolver.resolve("unknown"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("unknown");
    }

    private void setupResolver(Map<String, QdrantVectorStore> storeMap) {
        ReflectionTestUtils.setField(vectorStoreResolver, "embeddingProviderStoreMap", storeMap);
    }
}
