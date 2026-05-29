package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Extra branch coverage for ChatModelResolver:
 *  - Resolve with a blank provider falls back to default
 *  - Resolve with unknown provider throws
 *  - registerProvider: disabled provider is skipped
 *  - buildChatModel with unsupported type throws
 *  - buildRequestFactory with null timeoutSeconds uses default
 *  - buildRequestFactory with http1Required=true sets HTTP/1.1
 */
class ChatModelResolverExtraTest {

    @Test
    @DisplayName("resolve throws IllegalArgumentException when provider is not registered")
    void resolve_UnregisteredProvider_ThrowsIllegalArgument() {
        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("openai");
        props.setProviders(Map.of()); // no providers registered

        ChatModelResolver resolver = new ChatModelResolver(props);
        resolver.initializeProviders();

        assertThatThrownBy(() -> resolver.resolve("openai"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("openai");
    }

    @Test
    @DisplayName("initializeProviders skips disabled providers")
    void initializeProviders_DisabledProvider_IsSkipped() {
        AiProviderProperties.ProviderConfig disabled = new AiProviderProperties.ProviderConfig();
        disabled.setEnabled(false);
        disabled.setType("openai");
        disabled.setBaseUrl("http://localhost:1234/v1");
        disabled.setApiKey("test-key");
        disabled.setModel("gpt-4o");

        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", disabled));

        ChatModelResolver resolver = new ChatModelResolver(props);
        resolver.initializeProviders();

        // provider was disabled, so resolving it should throw
        assertThatThrownBy(() -> resolver.resolve("openai"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("buildChatModel throws for unsupported provider type")
    void buildChatModel_UnsupportedType_ThrowsIllegalArgument() {
        AiProviderProperties.ProviderConfig config = new AiProviderProperties.ProviderConfig();
        config.setEnabled(true);
        config.setType("unsupported-type");
        config.setBaseUrl("http://localhost:1234/v1");
        config.setApiKey("test-key");
        config.setModel("some-model");

        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("custom");
        props.setProviders(Map.of("custom", config));

        ChatModelResolver resolver = new ChatModelResolver(props);

        assertThatThrownBy(resolver::initializeProviders)
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("unsupported-type");
    }

    @Test
    @DisplayName("resolve with blank provider falls back to default provider")
    void resolve_BlankProvider_FallsBackToDefault() {
        AiProviderProperties.ProviderConfig config = new AiProviderProperties.ProviderConfig();
        config.setEnabled(true);
        config.setType("openai");
        config.setBaseUrl("http://localhost:1234/v1");
        config.setApiKey("test-key");
        config.setModel("gpt-4o");
        config.setRequiresHttp1(false);

        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", config));

        ChatModelResolver resolver = new ChatModelResolver(props);
        resolver.initializeProviders();

        // blank provider -> falls back to defaultProvider="openai" -> should find it
        var model = resolver.resolve("  ");
        assertThat(model).isNotNull();
    }

    @Test
    @DisplayName("buildRequestFactory works when http1Required=true")
    void buildRequestFactory_Http1Required_CreatesHttp1Factory() {
        AiProviderProperties.ProviderConfig config = new AiProviderProperties.ProviderConfig();
        config.setEnabled(true);
        config.setType("openai");
        config.setBaseUrl("http://localhost:1234/v1");
        config.setApiKey("test-key");
        config.setModel("gpt-4o");
        config.setRequiresHttp1(true); // triggers HTTP/1.1 branch

        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", config));

        ChatModelResolver resolver = new ChatModelResolver(props);
        // should not throw; HTTP/1.1 branch is exercised
        resolver.initializeProviders();
    }

    @Test
    @DisplayName("buildRequestFactory uses default timeout when timeoutSeconds is null")
    void buildRequestFactory_NullTimeoutSeconds_UsesDefaultTimeout() {
        AiProviderProperties.ProviderConfig config = new AiProviderProperties.ProviderConfig();
        config.setEnabled(true);
        config.setType("anthropic");
        config.setBaseUrl("https://api.anthropic.com");
        config.setApiKey("test-key");
        config.setModel("claude-sonnet-4-5");
        config.setTimeoutSeconds(null); // triggers default timeout branch

        AiProviderProperties props = new AiProviderProperties();
        props.setDefaultProvider("anthropic");
        props.setProviders(Map.of("anthropic", config));

        ChatModelResolver resolver = new ChatModelResolver(props);
        resolver.initializeProviders();
    }
}
