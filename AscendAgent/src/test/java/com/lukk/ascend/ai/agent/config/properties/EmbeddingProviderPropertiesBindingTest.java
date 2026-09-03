package com.lukk.ascend.ai.agent.config.properties;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Binds {@link EmbeddingProviderProperties} against the real {@code application.yaml} on the
 * classpath, unlike {@link PropertiesTest} which only exercises plain getters/setters. That
 * plain-POJO coverage cannot catch a mismatch between the YAML key and the field's binding
 * name, which is exactly the defect this test pins: {@code app.embedding.provider} in YAML
 * does not bind to a field named {@code defaultProvider}, so the field stayed null and every
 * prompt call omitting {@code embeddingProvider} failed with "Unknown embedding provider: 'null'".
 */
@SpringBootTest(classes = EmbeddingProviderProperties.class)
@EnableConfigurationProperties(EmbeddingProviderProperties.class)
class EmbeddingProviderPropertiesBindingTest {

    @Autowired
    private EmbeddingProviderProperties embeddingProviderProperties;

    @Test
    @DisplayName("app.embedding default provider binds to the configured YAML value, not null")
    void defaultProvider_BindsFromApplicationYaml() {
        assertThat(embeddingProviderProperties.getDefaultProvider()).isEqualTo("lmstudio");
    }
}
