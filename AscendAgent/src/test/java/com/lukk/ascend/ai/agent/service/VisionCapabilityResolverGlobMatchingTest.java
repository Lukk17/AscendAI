package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.agent.config.properties.VisionCapabilityProperties;
import org.junit.jupiter.api.DisplayName;
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
class VisionCapabilityResolverGlobMatchingTest {

    @Mock
    private VisionCapabilityProperties visionProperties;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private VisionCapabilityResolver resolver;

    @DisplayName("supports images denies when resolved model is blank")
    @Test
    void supportsImages_DeniesWhenResolvedModelIsBlank() {
        // given — no provider in the AiProviderProperties map -> resolveModel returns ""
        when(aiProviderProperties.getDefaultProvider()).thenReturn("openai");
        lenient().when(aiProviderProperties.getProviders()).thenReturn(Map.of());

        // then
        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @DisplayName("supports images denies when provider has no vision globs")
    @Test
    void supportsImages_DeniesWhenProviderHasNoVisionGlobs() {
        // given
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getDefaultProvider()).thenReturn("lmstudio");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of());

        // then
        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @DisplayName("supports images denies when provider has null globs list")
    @Test
    void supportsImages_DeniesWhenProviderHasNullGlobsList() {
        // given
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getDefaultProvider()).thenReturn("lmstudio");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        java.util.Map<String, java.util.List<String>> providersMap = new java.util.HashMap<>();
        providersMap.put("lmstudio", null);
        when(visionProperties.getProviders()).thenReturn(providersMap);

        // then
        assertThat(resolver.supportsImages(null, null)).isFalse();
    }

    @DisplayName("supports images allows when model matches glob case insensitive")
    @Test
    void supportsImages_AllowsWhenModelMatchesGlob_CaseInsensitive() {
        // given
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("Claude-Sonnet-4-6");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("anthropic", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));

        // then
        assertThat(resolver.supportsImages("anthropic", null)).isTrue();
    }

    @DisplayName("supports images denies when no glob matches model")
    @Test
    void supportsImages_DeniesWhenNoGlobMatchesModel() {
        // given
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel("local-llama");
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("lmstudio", cfg));
        when(visionProperties.getProviders()).thenReturn(Map.of("lmstudio", List.of("*-vl-*")));

        // then
        assertThat(resolver.supportsImages("lmstudio", null)).isFalse();
    }

    @DisplayName("supports images uses explicit model override over default")
    @Test
    void supportsImages_UsesExplicitModelOverride_OverDefault() {
        // given
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o*")));

        // then
        assertThat(resolver.supportsImages("openai", "gpt-4o-mini")).isTrue();
    }

    @DisplayName("supports images trims and lowercases provider")
    @Test
    void supportsImages_TrimsAndLowercasesProvider() {
        // given
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o*")));

        // then
        assertThat(resolver.supportsImages("  OpenAI  ", "gpt-4o")).isTrue();
    }
}
