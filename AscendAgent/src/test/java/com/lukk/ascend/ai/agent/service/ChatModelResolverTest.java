package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.anthropic.AnthropicChatModel;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.openai.OpenAiChatModel;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ChatModelResolverTest {

    private static final String PROVIDER_OPENAI = "openai";
    private static final String PROVIDER_ANTHROPIC = "anthropic";
    private static final String PROVIDER_UNKNOWN = "unknown";

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private ChatModelResolver chatModelResolver;

    @Test
    void resolve_WhenValidOpenAiProvider_ThenReturnsOpenAiChatModel() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_OPENAI, "openai");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_OPENAI, config));
        chatModelResolver.initializeProviders();

        // when
        ChatModel resolved = chatModelResolver.resolve(PROVIDER_OPENAI);

        // then
        assertThat(resolved).isInstanceOf(OpenAiChatModel.class);
    }

    @Test
    void resolve_WhenValidAnthropicProvider_ThenReturnsAnthropicChatModel() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_ANTHROPIC, "anthropic");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_ANTHROPIC, config));
        chatModelResolver.initializeProviders();

        // when
        ChatModel resolved = chatModelResolver.resolve(PROVIDER_ANTHROPIC);

        // then
        assertThat(resolved).isInstanceOf(AnthropicChatModel.class);
    }

    @Test
    void resolve_WhenUnknownProvider_ThenThrowsException() {
        // given
        when(aiProviderProperties.getProviders()).thenReturn(Map.of());
        chatModelResolver.initializeProviders();

        // when / then
        assertThatThrownBy(() -> chatModelResolver.resolve(PROVIDER_UNKNOWN))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("AI provider 'unknown' is not available");
    }

    @Test
    void resolve_WhenDisabledProvider_ThenThrowsException() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_OPENAI, "openai");
        config.setEnabled(false);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_OPENAI, config));
        chatModelResolver.initializeProviders();

        // when / then
        assertThatThrownBy(() -> chatModelResolver.resolve(PROVIDER_OPENAI))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("AI provider 'openai' is not available");
    }

    @Test
    void resolveDefault_WhenInvoked_ThenReturnsMappedDefaultProvider() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_OPENAI, "openai");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_OPENAI, config));
        when(aiProviderProperties.getDefaultProvider()).thenReturn(PROVIDER_OPENAI);
        chatModelResolver.initializeProviders();

        // when
        ChatModel resolved = chatModelResolver.resolveDefault();

        // then
        assertThat(resolved).isInstanceOf(OpenAiChatModel.class);
    }

    @Test
    void resolveDefault_WhenDefaultProviderMissing_ThenThrowsException() {
        // given
        when(aiProviderProperties.getProviders()).thenReturn(Map.of());
        when(aiProviderProperties.getDefaultProvider()).thenReturn(PROVIDER_UNKNOWN);
        chatModelResolver.initializeProviders();

        // when / then
        assertThatThrownBy(() -> chatModelResolver.resolveDefault())
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("AI provider 'unknown' is not available");
    }

    @Test
    void resolve_WhenProviderNull_ThenFallsBackToDefaultProvider() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_ANTHROPIC, "anthropic");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_ANTHROPIC, config));
        when(aiProviderProperties.getDefaultProvider()).thenReturn(PROVIDER_ANTHROPIC);
        chatModelResolver.initializeProviders();

        // when
        ChatModel resolved = chatModelResolver.resolve(null);

        // then
        assertThat(resolved).isInstanceOf(AnthropicChatModel.class);
    }
    
    @Test
    void initializeProviders_WhenUnsupportedType_ThenThrowsException() {
        // given
        ProviderConfig config = createValidConfig("weird", "unsupported-type");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("weird", config));

        // when / then
        assertThatThrownBy(() -> chatModelResolver.initializeProviders())
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unsupported AI provider type 'unsupported-type' for provider 'weird'");
    }

    @Test
    void resolve_WhenConfigRequiresHttp1_ThenInstantiatesSuccessfully() {
        // given
        ProviderConfig config = createValidConfig(PROVIDER_OPENAI, "openai");
        config.setRequiresHttp1(true);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of(PROVIDER_OPENAI, config));
        chatModelResolver.initializeProviders();

        // when
        ChatModel resolved = chatModelResolver.resolve(PROVIDER_OPENAI);

        // then
        assertThat(resolved).isInstanceOf(OpenAiChatModel.class);
    }

    private ProviderConfig createValidConfig(String modelName, String type) {
        ProviderConfig config = new ProviderConfig();
        config.setEnabled(true);
        config.setType(type);
        config.setBaseUrl("http://localhost");
        config.setApiKey("test-key");
        config.setModel(modelName);
        config.setMaxTokens(100);
        return config;
    }
}
