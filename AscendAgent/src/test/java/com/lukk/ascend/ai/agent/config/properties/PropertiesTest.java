package com.lukk.ascend.ai.agent.config.properties;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PropertiesTest {

    // Helpers

    private static AiProviderProperties.ProviderConfig buildProviderConfig() {
        AiProviderProperties.ProviderConfig cfg = new AiProviderProperties.ProviderConfig();
        cfg.setEnabled(true);
        cfg.setRequiresHttp1(true);
        cfg.setType("openai");
        cfg.setBaseUrl("http://x");
        cfg.setApiKey("k");
        cfg.setModel("gpt");
        cfg.setMemoryExtractionModel("gpt-mini");
        cfg.setDefaultEmbedding("text-embedding");
        cfg.setTemperature(0.7d);
        cfg.setMaxTokens(1024);
        cfg.setTimeoutSeconds(30L);
        return cfg;
    }

    private static EmbeddingProviderProperties.EmbeddingConfig buildEmbeddingConfig() {
        EmbeddingProviderProperties.EmbeddingConfig cfg = new EmbeddingProviderProperties.EmbeddingConfig();
        cfg.setType("openai");
        cfg.setBaseUrl("http://e");
        cfg.setApiKey("k");
        cfg.setModel("text-embedding");
        cfg.setDimensions(1536);
        return cfg;
    }

    private static PromptCacheProperties.ProviderCache buildProviderCache(boolean enabled) {
        PromptCacheProperties.ProviderCache pc = new PromptCacheProperties.ProviderCache();
        pc.setEnabled(enabled);
        return pc;
    }

    // AiProviderProperties

    @Test
    @DisplayName("AiProviderProperties getters return values set via setters")
    void aiProviderProperties_GettersAndSetters() {
        // given
        AiProviderProperties.ProviderConfig cfg = buildProviderConfig();
        AiProviderProperties props = new AiProviderProperties();

        // when
        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", cfg));

        // then
        assertThat(props.getDefaultProvider()).isEqualTo("openai");
        assertThat(props.getProviders()).containsKey("openai");
        AiProviderProperties.ProviderConfig got = props.getProviders().get("openai");
        assertThat(got.isEnabled()).isTrue();
        assertThat(got.isRequiresHttp1()).isTrue();
        assertThat(got.getType()).isEqualTo("openai");
        assertThat(got.getBaseUrl()).isEqualTo("http://x");
        assertThat(got.getApiKey()).isEqualTo("k");
        assertThat(got.getModel()).isEqualTo("gpt");
        assertThat(got.getMemoryExtractionModel()).isEqualTo("gpt-mini");
        assertThat(got.getDefaultEmbedding()).isEqualTo("text-embedding");
        assertThat(got.getTemperature()).isEqualTo(0.7d);
        assertThat(got.getMaxTokens()).isEqualTo(1024);
        assertThat(got.getTimeoutSeconds()).isEqualTo(30L);
    }

    // EmbeddingProviderProperties

    @Test
    @DisplayName("EmbeddingProviderProperties active accessors resolve the default provider")
    void embeddingProviderProperties_ActiveAccessorsResolveDefault() {
        // given
        EmbeddingProviderProperties.EmbeddingConfig cfg = buildEmbeddingConfig();
        EmbeddingProviderProperties props = new EmbeddingProviderProperties();

        // when
        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", cfg));

        // then
        assertThat(props.getActiveProvider()).isSameAs(cfg);
        assertThat(props.getActiveDimensions()).isEqualTo(1536);
        assertThat(props.getActiveCollectionName()).isEqualTo("ascendai-1536");

        assertThat(cfg.getType()).isEqualTo("openai");
        assertThat(cfg.getBaseUrl()).isEqualTo("http://e");
        assertThat(cfg.getApiKey()).isEqualTo("k");
        assertThat(cfg.getModel()).isEqualTo("text-embedding");
        assertThat(cfg.getDimensions()).isEqualTo(1536);
    }

    @Test
    @DisplayName("EmbeddingProviderProperties returns null active provider when key is missing")
    void embeddingProviderProperties_ActiveProviderReturnsNull_WhenMissing() {
        // given
        EmbeddingProviderProperties props = new EmbeddingProviderProperties();
        props.setDefaultProvider("missing");
        props.setProviders(Map.of());

        // then
        assertThat(props.getActiveProvider()).isNull();
        assertThatThrownBy(props::getActiveDimensions).isInstanceOf(NullPointerException.class);
    }

    // RagProperties

    @Test
    @DisplayName("RagProperties exposes correct defaults and accepts new values via setters")
    void ragProperties_DefaultsAndSetters() {
        // given
        RagProperties props = new RagProperties();

        // then — defaults
        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getTopK()).isEqualTo(5);
        assertThat(props.getSimilarityThreshold()).isEqualTo(0.4d);
        assertThat(props.getMaxContextChars()).isEqualTo(4000);
        assertThat(props.getSourceAttachments()).isNotNull();
        assertThat(props.getSourceAttachments().isEnabled()).isTrue();
        assertThat(props.getSourceAttachments().getPresignTtl()).isEqualTo(java.time.Duration.ofMinutes(15));
        assertThat(props.getSourceAttachments().getMaxFileSize())
                .isEqualTo(org.springframework.util.unit.DataSize.ofMegabytes(25));

        // when — setters
        props.setEnabled(false);
        props.setTopK(10);
        props.setSimilarityThreshold(0.8d);
        props.setMaxContextChars(2000);

        RagProperties.SourceAttachments sa = new RagProperties.SourceAttachments();
        sa.setEnabled(false);
        sa.setPresignTtl(java.time.Duration.ofMinutes(5));
        sa.setMaxFileSize(org.springframework.util.unit.DataSize.ofMegabytes(50));
        props.setSourceAttachments(sa);

        // then — updated values
        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getTopK()).isEqualTo(10);
        assertThat(props.getSimilarityThreshold()).isEqualTo(0.8d);
        assertThat(props.getMaxContextChars()).isEqualTo(2000);
        assertThat(props.getSourceAttachments().isEnabled()).isFalse();
        assertThat(props.getSourceAttachments().getPresignTtl()).isEqualTo(java.time.Duration.ofMinutes(5));
        assertThat(props.getSourceAttachments().getMaxFileSize())
                .isEqualTo(org.springframework.util.unit.DataSize.ofMegabytes(50));
    }

    // SemanticMemoryProperties

    @Test
    @DisplayName("SemanticMemoryProperties exposes correct defaults and accepts updated values")
    void semanticMemoryProperties_DefaultsAndSetters() {
        // given
        SemanticMemoryProperties props = new SemanticMemoryProperties();

        // then — defaults
        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getBaseUrl()).isEqualTo("http://localhost:7020");
        assertThat(props.getSearchLimit()).isEqualTo(5);

        // when
        props.setEnabled(false);
        props.setBaseUrl("http://other:7777");
        props.setSearchLimit(20);

        // then
        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getBaseUrl()).isEqualTo("http://other:7777");
        assertThat(props.getSearchLimit()).isEqualTo(20);
    }

    // VectorStoreProperties

    @Test
    @DisplayName("VectorStoreProperties getters and setters work correctly for collection config")
    void vectorStoreProperties_GettersAndSetters() {
        // given
        VectorStoreProperties props = new VectorStoreProperties();
        VectorStoreProperties.CollectionConfig cfg = new VectorStoreProperties.CollectionConfig();

        // when
        cfg.setName("ascendai-768");
        cfg.setSize(768);
        props.setCollections(List.of(cfg));

        // then
        assertThat(props.getCollections()).hasSize(1);
        assertThat(props.getCollections().getFirst().getName()).isEqualTo("ascendai-768");
        assertThat(props.getCollections().getFirst().getSize()).isEqualTo(768);
    }

    // VisionCapabilityProperties

    @Test
    @DisplayName("VisionCapabilityProperties stores provider-to-glob-patterns map")
    void visionCapabilityProperties_GettersAndSetters() {
        // given
        VisionCapabilityProperties props = new VisionCapabilityProperties();
        Map<String, List<String>> map = Map.of(
                "openai", List.of("gpt-4o*"),
                "anthropic", List.of("claude-*"));

        // when
        props.setProviders(map);

        // then
        assertThat(props.getProviders()).hasSize(2);
        assertThat(props.getProviders().get("openai")).containsExactly("gpt-4o*");
        assertThat(props.getProviders().get("anthropic")).containsExactly("claude-*");
    }

    // PromptCacheProperties

    @Test
    @DisplayName("PromptCacheProperties master toggle and per-provider toggles interact correctly")
    void promptCacheProperties_DefaultsTogglesAndSetters() {
        // given
        PromptCacheProperties props = new PromptCacheProperties();

        // then — defaults
        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getProviders()).isEmpty();
        assertThat(props.isProviderEnabled("anthropic")).isTrue();

        // when — disable anthropic per-provider
        props.setProviders(Map.of("anthropic", buildProviderCache(false)));

        // then
        assertThat(props.isProviderEnabled("anthropic")).isFalse();
        assertThat(props.isProviderEnabled("openai")).isTrue();

        // when — disable master
        props.setEnabled(false);

        // then — all disabled when master is off
        assertThat(props.isProviderEnabled("openai")).isFalse();
        assertThat(props.isProviderEnabled("anthropic")).isFalse();
    }

    // ChatHistoryCompactionProperties

    @Test
    @DisplayName("ChatHistoryCompactionProperties exposes correct defaults and accepts updated values")
    void chatHistoryCompactionProperties_DefaultsAndSetters() {
        // given
        ChatHistoryCompactionProperties props = new ChatHistoryCompactionProperties();

        // then — defaults
        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getTurnTrigger()).isEqualTo(20);
        assertThat(props.getTokenTriggerFraction()).isEqualTo(0.5d);
        assertThat(props.getKeepRecentTurns()).isEqualTo(8);
        assertThat(props.getMaxSummaryTokens()).isEqualTo(800);
        assertThat(props.getProviderDefaults()).isEmpty();

        // when
        props.setEnabled(false);
        props.setTurnTrigger(50);
        props.setTokenTriggerFraction(0.7d);
        props.setKeepRecentTurns(12);
        props.setMaxSummaryTokens(1200);
        props.setProviderDefaults(Map.of("anthropic", "claude-haiku-4-5"));

        // then
        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getTurnTrigger()).isEqualTo(50);
        assertThat(props.getTokenTriggerFraction()).isEqualTo(0.7d);
        assertThat(props.getKeepRecentTurns()).isEqualTo(12);
        assertThat(props.getMaxSummaryTokens()).isEqualTo(1200);
        assertThat(props.getProviderDefaults()).containsEntry("anthropic", "claude-haiku-4-5");
    }

    // ChatHistoryProperties

    @Test
    @DisplayName("ChatHistoryProperties exposes correct defaults and accepts updated values")
    void chatHistoryProperties_DefaultsAndSetters() {
        // given
        ChatHistoryProperties props = new ChatHistoryProperties();

        // then — defaults
        assertThat(props.getMaxSize()).isEqualTo(5);
        assertThat(props.getTtl()).isEqualTo(java.time.Duration.ofHours(24));
        assertThat(props.getRedis()).isNotNull();
        assertThat(props.getRedis().isEnabled()).isTrue();
        assertThat(props.getPostgres()).isNotNull();
        assertThat(props.getPostgres().isEnabled()).isTrue();

        // when
        props.setMaxSize(20);
        props.setTtl(java.time.Duration.ofMinutes(15));
        ChatHistoryProperties.Redis redis = new ChatHistoryProperties.Redis();
        redis.setEnabled(false);
        props.setRedis(redis);
        ChatHistoryProperties.Postgres postgres = new ChatHistoryProperties.Postgres();
        postgres.setEnabled(false);
        props.setPostgres(postgres);

        // then
        assertThat(props.getMaxSize()).isEqualTo(20);
        assertThat(props.getTtl()).isEqualTo(java.time.Duration.ofMinutes(15));
        assertThat(props.getRedis().isEnabled()).isFalse();
        assertThat(props.getPostgres().isEnabled()).isFalse();
    }

    // IngestionUploadProperties

    @Test
    @DisplayName("IngestionUploadProperties defaults to empty allowed-mime list and accepts new values")
    void ingestionUploadProperties_DefaultsAndSetters() {
        // given
        IngestionUploadProperties props = new IngestionUploadProperties();

        // then — default
        assertThat(props.getAllowedMimeTypes()).isEmpty();

        // when
        props.setAllowedMimeTypes(List.of("application/pdf", "text/markdown"));

        // then
        assertThat(props.getAllowedMimeTypes()).containsExactly("application/pdf", "text/markdown");

        // when — null
        props.setAllowedMimeTypes(null);

        // then
        assertThat(props.getAllowedMimeTypes()).isNull();
    }
}
