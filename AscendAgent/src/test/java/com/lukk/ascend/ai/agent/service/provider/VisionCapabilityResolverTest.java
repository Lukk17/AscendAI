package com.lukk.ascend.ai.agent.service.provider;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties.ProviderConfig;
import com.lukk.ascend.ai.agent.config.properties.VisionCapabilityProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class VisionCapabilityResolverTest {

    @Mock
    private VisionCapabilityProperties visionProperties;

    @Mock
    private AiProviderProperties aiProviderProperties;

    @InjectMocks
    private VisionCapabilityResolver resolver;

    @Test
    @DisplayName("supportsImages returns true when model matches a prefix wildcard pattern like claude-*")
    void supportsImages_WhenProviderHasGlob_AndModelMatchesPrefixWildcard_ThenTrue() {
        // given — claude-* matches claude-sonnet-4-6
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));

        // when
        boolean supports = resolver.supportsImages("anthropic", "claude-sonnet-4-6");

        // then
        assertThat(supports).isTrue();
    }

    @Test
    @DisplayName("supportsImages returns true when model matches a gpt-4o* prefix glob")
    void supportsImages_WhenGptPrefixGlobMatches_ThenTrue() {
        // given — gpt-4o* matches gpt-4o-mini
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o*")));

        boolean supports = resolver.supportsImages("openai", "gpt-4o-mini");

        assertThat(supports).isTrue();
    }

    @Test
    @DisplayName("supportsImages returns true when model matches a middle-wildcard pattern like *-vl-*")
    void supportsImages_WhenMiddleWildcardMatches_ThenTrue() {
        // given — *-vl-* matches qwen3-vl-4b
        when(visionProperties.getProviders()).thenReturn(Map.of("lmstudio", List.of("*-vl-*")));

        boolean supports = resolver.supportsImages("lmstudio", "qwen3-vl-4b");

        assertThat(supports).isTrue();
    }

    @Test
    @DisplayName("supportsImages returns false when model does not match the provider's glob pattern")
    void supportsImages_WhenGlobDoesNotMatchModel_ThenFalse() {
        // given — claude-* does NOT match gpt-4o
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));

        boolean supports = resolver.supportsImages("anthropic", "gpt-4o");

        assertThat(supports).isFalse();
    }

    @Test
    @DisplayName("supportsImages returns false when the provider has an empty pattern list")
    void supportsImages_WhenProviderHasEmptyPatternList_ThenFalse() {
        // given — empty list means no images allowed
        when(visionProperties.getProviders()).thenReturn(Map.of("minimax", List.of()));

        boolean supports = resolver.supportsImages("minimax", "MiniMax-M2.7");

        assertThat(supports).isFalse();
    }

    @Test
    @DisplayName("supportsImages returns false when model is null")
    void supportsImages_WhenModelIsNull_ThenFalse() {
        // given
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));
        ProviderConfig cfg = new ProviderConfig();
        cfg.setModel(null);
        when(aiProviderProperties.getProviders()).thenReturn(Map.of("anthropic", cfg));

        boolean supports = resolver.supportsImages("anthropic", null);

        assertThat(supports).isFalse();
    }

    @Test
    @DisplayName("supportsImages returns false when the provider key is not in the vision properties")
    void supportsImages_WhenProviderMissingFromConfig_ThenFalse() {
        // given
        when(visionProperties.getProviders()).thenReturn(Map.of("anthropic", List.of("claude-*")));

        boolean supports = resolver.supportsImages("unknown-provider", "some-model");

        assertThat(supports).isFalse();
    }

    @Test
    @DisplayName("supportsImages returns true when model exactly matches a pattern with no wildcards")
    void supportsImages_WhenExactPatternMatches_ThenTrue() {
        // given — pattern without wildcards is an exact match
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o-mini")));

        boolean supports = resolver.supportsImages("openai", "gpt-4o-mini");

        assertThat(supports).isTrue();
    }

    @Test
    @DisplayName("supportsImages returns false when exact pattern does not match a different model")
    void supportsImages_WhenExactPatternDoesNotMatchDifferentModel_ThenFalse() {
        when(visionProperties.getProviders()).thenReturn(Map.of("openai", List.of("gpt-4o-mini")));

        boolean supports = resolver.supportsImages("openai", "gpt-4o");

        assertThat(supports).isFalse();
    }
}
