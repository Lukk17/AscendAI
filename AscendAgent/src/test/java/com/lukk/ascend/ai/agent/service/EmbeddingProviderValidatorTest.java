package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.EmbeddingProviderProperties.EmbeddingConfig;
import com.lukk.ascend.ai.agent.exception.IncompatibleEmbeddingException;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EmbeddingProviderValidatorTest {

    private static final String CHAT_PROVIDER_LMSTUDIO = "lmstudio";
    private static final String CHAT_PROVIDER_OPENAI = "openai";
    private static final String CHAT_PROVIDER_GEMINI = "gemini";

    private static final String EMBED_PROVIDER_LMSTUDIO = "lmstudio";
    private static final String EMBED_PROVIDER_OPENAI = "openai";

    @Mock
    private EmbeddingProviderProperties embeddingProviderProperties;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private EmbeddingProviderValidator validator;

    @Test
    @DisplayName("validate passes when lmstudio chat provider uses lmstudio embedding provider")
    void validate_WhenLmstudioChatAndLmstudioEmbedding_ThenDoesNotThrowException() {
        // given
        setupProviderMocks(CHAT_PROVIDER_LMSTUDIO, EMBED_PROVIDER_LMSTUDIO, 768);

        // then
        assertThatCode(() -> validator.validate(CHAT_PROVIDER_LMSTUDIO, EMBED_PROVIDER_LMSTUDIO))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("validate passes when gemini chat provider uses lmstudio embedding provider")
    void validate_WhenGeminiChatAndLmstudioEmbedding_ThenDoesNotThrowException() {
        // given
        setupProviderMocks(CHAT_PROVIDER_GEMINI, EMBED_PROVIDER_LMSTUDIO, 768);

        // then
        assertThatCode(() -> validator.validate(CHAT_PROVIDER_GEMINI, EMBED_PROVIDER_LMSTUDIO))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("validate passes when openai chat provider uses openai embedding provider")
    void validate_WhenOpenAiChatAndOpenAiEmbedding_ThenDoesNotThrowException() {
        // given
        setupProviderMocks(CHAT_PROVIDER_OPENAI, EMBED_PROVIDER_OPENAI, 1536);

        // then
        assertThatCode(() -> validator.validate(CHAT_PROVIDER_OPENAI, EMBED_PROVIDER_OPENAI))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("validate throws IncompatibleEmbeddingException when lmstudio chat uses openai embedding")
    void validate_WhenLmstudioChatAndOpenAiEmbedding_ThenThrowsIncompatibleEmbeddingException() {
        // given
        setupProviderMocks(CHAT_PROVIDER_LMSTUDIO, EMBED_PROVIDER_OPENAI, 1536);

        // then
        assertThatThrownBy(() -> validator.validate(CHAT_PROVIDER_LMSTUDIO, EMBED_PROVIDER_OPENAI))
                .isInstanceOf(IncompatibleEmbeddingException.class)
                .hasMessageContaining("Chat provider 'lmstudio' is incompatible with embedding provider 'openai'");
    }

    @Test
    @DisplayName("validate throws IncompatibleEmbeddingException when openai chat uses lmstudio embedding")
    void validate_WhenOpenAiChatAndLmstudioEmbedding_ThenThrowsIncompatibleEmbeddingException() {
        // given
        setupProviderMocks(CHAT_PROVIDER_OPENAI, EMBED_PROVIDER_LMSTUDIO, 768);

        // then
        assertThatThrownBy(() -> validator.validate(CHAT_PROVIDER_OPENAI, EMBED_PROVIDER_LMSTUDIO))
                .isInstanceOf(IncompatibleEmbeddingException.class)
                .hasMessageContaining("Chat provider 'openai' is incompatible with embedding provider 'lmstudio'");
    }

    @Test
    @DisplayName("validate resolves default providers and passes when null is passed for both")
    void validate_WhenNullProvidersPassed_ThenResolvesDefaultsAndValidates() {
        // given
        when(aiProviderProperties.getDefaultProvider()).thenReturn(CHAT_PROVIDER_LMSTUDIO);
        when(embeddingProviderProperties.getDefaultProvider()).thenReturn(EMBED_PROVIDER_LMSTUDIO);

        EmbeddingConfig embedConfig = new EmbeddingConfig();
        embedConfig.setDimensions(768);
        when(embeddingProviderProperties.getProviders()).thenReturn(Map.of(EMBED_PROVIDER_LMSTUDIO, embedConfig));

        // then
        assertThatCode(() -> validator.validate(null, null))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("validate throws when null providers resolve to incompatible defaults")
    void validate_WhenNullProvidersResolveToIncompatibleDefaults_ThenThrowsException() {
        // given
        when(aiProviderProperties.getDefaultProvider()).thenReturn(CHAT_PROVIDER_LMSTUDIO);
        when(embeddingProviderProperties.getDefaultProvider()).thenReturn(EMBED_PROVIDER_OPENAI);

        EmbeddingConfig embedConfig = new EmbeddingConfig();
        embedConfig.setDimensions(1536);
        when(embeddingProviderProperties.getProviders()).thenReturn(Map.of(EMBED_PROVIDER_OPENAI, embedConfig));

        // then
        assertThatThrownBy(() -> validator.validate(null, null))
                .isInstanceOf(IncompatibleEmbeddingException.class);
    }

    @Test
    @DisplayName("validate throws IllegalArgumentException for an unknown embedding provider")
    void validate_WhenUnknownEmbeddingProvider_ThenThrowsIllegalArgumentException() {
        // given
        when(aiProviderProperties.getDefaultProvider()).thenReturn(CHAT_PROVIDER_GEMINI);
        when(embeddingProviderProperties.getProviders()).thenReturn(Map.of()); // No embeddings mapped

        // then
        assertThatThrownBy(() -> validator.validate(CHAT_PROVIDER_GEMINI, "nonexistent"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown embedding provider: 'nonexistent'");
    }

    @Test
    @DisplayName("validate throws IllegalArgumentException when default embedding provider is not in the map")
    void validate_WhenResolvingUnknownDefaultEmbeddingProvider_ThenThrowsIllegalArgumentException() {
        // given
        when(aiProviderProperties.getDefaultProvider()).thenReturn(CHAT_PROVIDER_GEMINI);
        when(embeddingProviderProperties.getDefaultProvider()).thenReturn("nonexistent");
        when(embeddingProviderProperties.getProviders()).thenReturn(Map.of());

        // then
        assertThatThrownBy(() -> validator.validate(null, null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown embedding provider: 'nonexistent'");
    }

    private void setupProviderMocks(String chatProvider, String embedProvider, int dimensions) {
        when(aiProviderProperties.getDefaultProvider()).thenReturn(chatProvider);

        EmbeddingConfig embedConfig = new EmbeddingConfig();
        embedConfig.setDimensions(dimensions);
        when(embeddingProviderProperties.getProviders()).thenReturn(Map.of(embedProvider, embedConfig));
    }
}
