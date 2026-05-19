package com.lukk.ascend.ai.agent.config.properties;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PropertiesTest {

    @Test
    void aiProviderProperties_GettersAndSetters() {
        AiProviderProperties props = new AiProviderProperties();
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

        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", cfg));

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

    @Test
    void embeddingProviderProperties_ActiveAccessorsResolveDefault() {
        EmbeddingProviderProperties props = new EmbeddingProviderProperties();
        EmbeddingProviderProperties.EmbeddingConfig cfg = new EmbeddingProviderProperties.EmbeddingConfig();

        cfg.setType("openai");
        cfg.setBaseUrl("http://e");
        cfg.setApiKey("k");
        cfg.setModel("text-embedding");
        cfg.setDimensions(1536);

        props.setDefaultProvider("openai");
        props.setProviders(Map.of("openai", cfg));

        assertThat(props.getActiveProvider()).isSameAs(cfg);
        assertThat(props.getActiveDimensions()).isEqualTo(1536);
        assertThat(props.getActiveCollectionName()).isEqualTo("ascendai-1536");

        // exercise child config getters
        assertThat(cfg.getType()).isEqualTo("openai");
        assertThat(cfg.getBaseUrl()).isEqualTo("http://e");
        assertThat(cfg.getApiKey()).isEqualTo("k");
        assertThat(cfg.getModel()).isEqualTo("text-embedding");
        assertThat(cfg.getDimensions()).isEqualTo(1536);
    }

    @Test
    void embeddingProviderProperties_ActiveProviderReturnsNull_WhenMissing() {
        EmbeddingProviderProperties props = new EmbeddingProviderProperties();
        props.setDefaultProvider("missing");
        props.setProviders(Map.of());

        assertThat(props.getActiveProvider()).isNull();
        assertThatThrownBy(props::getActiveDimensions).isInstanceOf(NullPointerException.class);
    }

    @Test
    void ragProperties_DefaultsAndSetters() {
        RagProperties props = new RagProperties();

        // defaults
        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getTopK()).isEqualTo(5);
        assertThat(props.getSimilarityThreshold()).isEqualTo(0.4d);
        assertThat(props.getMaxContextChars()).isEqualTo(4000);
        assertThat(props.getSourceAttachments()).isNotNull();
        assertThat(props.getSourceAttachments().isEnabled()).isTrue();
        assertThat(props.getSourceAttachments().getPresignTtl()).isEqualTo(java.time.Duration.ofMinutes(15));
        assertThat(props.getSourceAttachments().getMaxFileSize())
                .isEqualTo(org.springframework.util.unit.DataSize.ofMegabytes(25));

        // setters
        props.setEnabled(false);
        props.setTopK(10);
        props.setSimilarityThreshold(0.8d);
        props.setMaxContextChars(2000);

        RagProperties.SourceAttachments sa = new RagProperties.SourceAttachments();
        sa.setEnabled(false);
        sa.setPresignTtl(java.time.Duration.ofMinutes(5));
        sa.setMaxFileSize(org.springframework.util.unit.DataSize.ofMegabytes(50));
        props.setSourceAttachments(sa);

        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getTopK()).isEqualTo(10);
        assertThat(props.getSimilarityThreshold()).isEqualTo(0.8d);
        assertThat(props.getMaxContextChars()).isEqualTo(2000);
        assertThat(props.getSourceAttachments().isEnabled()).isFalse();
        assertThat(props.getSourceAttachments().getPresignTtl()).isEqualTo(java.time.Duration.ofMinutes(5));
        assertThat(props.getSourceAttachments().getMaxFileSize())
                .isEqualTo(org.springframework.util.unit.DataSize.ofMegabytes(50));
    }

    @Test
    void semanticMemoryProperties_DefaultsAndSetters() {
        SemanticMemoryProperties props = new SemanticMemoryProperties();

        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getBaseUrl()).isEqualTo("http://localhost:7020");
        assertThat(props.getSearchLimit()).isEqualTo(5);

        props.setEnabled(false);
        props.setBaseUrl("http://other:7777");
        props.setSearchLimit(20);

        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getBaseUrl()).isEqualTo("http://other:7777");
        assertThat(props.getSearchLimit()).isEqualTo(20);
    }

    @Test
    void vectorStoreProperties_GettersAndSetters() {
        VectorStoreProperties props = new VectorStoreProperties();
        VectorStoreProperties.CollectionConfig cfg = new VectorStoreProperties.CollectionConfig();
        cfg.setName("ascendai-768");
        cfg.setSize(768);

        props.setCollections(List.of(cfg));

        assertThat(props.getCollections()).hasSize(1);
        assertThat(props.getCollections().get(0).getName()).isEqualTo("ascendai-768");
        assertThat(props.getCollections().get(0).getSize()).isEqualTo(768);
    }

    @Test
    void visionCapabilityProperties_GettersAndSetters() {
        VisionCapabilityProperties props = new VisionCapabilityProperties();
        Map<String, List<String>> map = Map.of(
                "openai", List.of("gpt-4o*"),
                "anthropic", List.of("claude-*"));

        props.setProviders(map);

        assertThat(props.getProviders()).hasSize(2);
        assertThat(props.getProviders().get("openai")).containsExactly("gpt-4o*");
        assertThat(props.getProviders().get("anthropic")).containsExactly("claude-*");
    }

    @Test
    void promptCacheProperties_DefaultsTogglesAndSetters() {
        PromptCacheProperties props = new PromptCacheProperties();

        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getProviders()).isEmpty();
        assertThat(props.isProviderEnabled("anthropic")).isTrue();

        PromptCacheProperties.ProviderCache anth = new PromptCacheProperties.ProviderCache();
        anth.setEnabled(false);
        props.setProviders(Map.of("anthropic", anth));
        assertThat(props.isProviderEnabled("anthropic")).isFalse();
        assertThat(props.isProviderEnabled("openai")).isTrue();

        props.setEnabled(false);
        assertThat(props.isProviderEnabled("openai")).isFalse();
        assertThat(props.isProviderEnabled("anthropic")).isFalse();
    }

    @Test
    void chatHistoryCompactionProperties_DefaultsAndSetters() {
        ChatHistoryCompactionProperties props = new ChatHistoryCompactionProperties();

        assertThat(props.isEnabled()).isTrue();
        assertThat(props.getTurnTrigger()).isEqualTo(20);
        assertThat(props.getTokenTriggerFraction()).isEqualTo(0.5d);
        assertThat(props.getKeepRecentTurns()).isEqualTo(8);
        assertThat(props.getMaxSummaryTokens()).isEqualTo(800);
        assertThat(props.getProviderDefaults()).isEmpty();

        props.setEnabled(false);
        props.setTurnTrigger(50);
        props.setTokenTriggerFraction(0.7d);
        props.setKeepRecentTurns(12);
        props.setMaxSummaryTokens(1200);
        props.setProviderDefaults(Map.of("anthropic", "claude-haiku-4-5"));

        assertThat(props.isEnabled()).isFalse();
        assertThat(props.getTurnTrigger()).isEqualTo(50);
        assertThat(props.getTokenTriggerFraction()).isEqualTo(0.7d);
        assertThat(props.getKeepRecentTurns()).isEqualTo(12);
        assertThat(props.getMaxSummaryTokens()).isEqualTo(1200);
        assertThat(props.getProviderDefaults()).containsEntry("anthropic", "claude-haiku-4-5");
    }

    @Test
    void chatHistoryProperties_DefaultsAndSetters() {
        ChatHistoryProperties props = new ChatHistoryProperties();

        assertThat(props.getMaxSize()).isEqualTo(5);
        assertThat(props.getTtl()).isEqualTo(java.time.Duration.ofHours(24));
        assertThat(props.getRedis()).isNotNull();
        assertThat(props.getRedis().isEnabled()).isTrue();
        assertThat(props.getPostgres()).isNotNull();
        assertThat(props.getPostgres().isEnabled()).isTrue();

        props.setMaxSize(20);
        props.setTtl(java.time.Duration.ofMinutes(15));
        ChatHistoryProperties.Redis redis = new ChatHistoryProperties.Redis();
        redis.setEnabled(false);
        props.setRedis(redis);
        ChatHistoryProperties.Postgres postgres = new ChatHistoryProperties.Postgres();
        postgres.setEnabled(false);
        props.setPostgres(postgres);

        assertThat(props.getMaxSize()).isEqualTo(20);
        assertThat(props.getTtl()).isEqualTo(java.time.Duration.ofMinutes(15));
        assertThat(props.getRedis().isEnabled()).isFalse();
        assertThat(props.getPostgres().isEnabled()).isFalse();
    }

    @Test
    void ingestionUploadProperties_DefaultsAndSetters() {
        IngestionUploadProperties props = new IngestionUploadProperties();

        assertThat(props.getAllowedMimeTypes()).isEmpty();

        props.setAllowedMimeTypes(List.of("application/pdf", "text/markdown"));
        assertThat(props.getAllowedMimeTypes()).containsExactly("application/pdf", "text/markdown");

        props.setAllowedMimeTypes(null);
        assertThat(props.getAllowedMimeTypes()).isNull();
    }
}
