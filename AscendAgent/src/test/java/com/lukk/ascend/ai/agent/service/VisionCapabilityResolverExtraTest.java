package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.agent.config.properties.VisionCapabilityProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class VisionCapabilityResolverExtraTest {

    @Mock
    private VisionCapabilityProperties visionProperties;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private VisionCapabilityResolver resolver;

    @Test
    void supportsImages_DeniesWhenResolvedModelIsBlank() {
        // No provider in the AiProviderProperties map → resolveModel returns "".
        when(aiProviderProperties.getDefaultProvider()).thenReturn("openai");
        lenient().when(aiProviderProperties.getProviders()).thenReturn(Map.of());

        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @Test
    void supportsImages_DeniesWhenProviderHasNoVisionGlobs() {
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getDefaultProvider()).thenReturn("lmstudio");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of());

        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @Test
    void supportsImages_DeniesWhenProviderHasNullGlobsList() {
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getDefaultProvider()).thenReturn("lmstudio");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        // Map with null value for the provider
        java.util.Map<String, java.util.List<String>> providersMap = new java.util.HashMap<>();
        providersMap.put("lmstudio", null);
        when(visionProperties.getProviders()).thenReturn(providersMap);

        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @Test
    void supportsImages_AllowsWhenModelMatchesGlob_CaseInsensitive() {
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("Claude-Sonnet-4-6");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("anthropic", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));

        assertThat(resolver.supportsImages("anthropic", null)).isTrue();
    }

    @Test
    void supportsImages_DeniesWhenNoGlobMatchesModel() {
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of("lmstudio", List.of("*-vl-*")));

        assertThat(resolver.supportsImages("lmstudio", null)).isFalse();
    }

    @Test
    void supportsImages_UsesExplicitModelOverride_OverDefault() {
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o*")));

        assertThat(resolver.supportsImages("openai", "gpt-4o-mini")).isTrue();
    }

    @Test
    void supportsImages_TrimsAndLowercasesProvider() {
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o*")));

        assertThat(resolver.supportsImages("  OpenAI  ", "gpt-4o")).isTrue();
    }
}
