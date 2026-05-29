package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for RagRetrievalService: null score filtered out,
 * text null/blank skip in context building, key from IngestionMetadataKeys.SOURCE fallback,
 * displayName from IngestionMetadataKeys.TITLE fallback.
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RagRetrievalServiceExtraTest {

    private static final String DEFAULT_QUERY = "test query";
    private static final String EMBED_PROVIDER = "openai";
    private static final String DEFAULT_BUCKET = "knowledge-base";

    @Mock
    private VectorStoreResolver vectorStoreResolver;

    @Mock
    private RagProperties ragProperties;

    @Mock
    private VectorStore vectorStore;

    private RagRetrievalService service;

    @BeforeEach
    void setUp() {
        service = new RagRetrievalService(vectorStoreResolver, ragProperties, DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve filters out candidates with null score")
    void retrieve_NullScoreDocument_IsFiltered() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document nullScore = mockDoc("text", null, Map.of("source", "file.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(nullScore));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.context()).isEmpty();
    }

    @Test
    @DisplayName("retrieve skips null/blank text chunks when building context block")
    void retrieve_BlankTextDocument_SkippedInContext() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document blank = mockDoc("   ", 0.9, Map.of("source", "blank.txt"));
        Document real = mockDoc("Actual content.", 0.85, Map.of("source", "real.txt"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(blank, real));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.context()).contains("Actual content.");
        assertThat(result.context()).doesNotContain("   ");
    }

    @Test
    @DisplayName("retrieve skips null text chunks when building context block")
    void retrieve_NullTextDocument_SkippedInContext() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document nullText = mockDoc(null, 0.9, Map.of("source", "nulltext.txt"));
        Document real = mockDoc("Valid text.", 0.85, Map.of("source", "real.txt"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(nullText, real));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.context()).contains("Valid text.");
    }

    @Test
    @DisplayName("retrieve uses IngestionMetadataKeys.SOURCE fallback when 'key' metadata is absent")
    void retrieve_KeyMetadataAbsent_FallsBackToSourceMetadata() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // No "key" in metadata, only "source"
        Document doc = mockDoc("Content.", 0.9, Map.of("source", "docs/readme.md"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().key()).isEqualTo("docs/readme.md");
    }

    @Test
    @DisplayName("retrieve uses IngestionMetadataKeys.TITLE as displayName fallback when displayName is absent")
    void retrieve_DisplayNameAbsent_FallsBackToTitleMetadata() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // "title" is present as fallback for displayName
        Document doc = mockDoc("Content.", 0.9, Map.of("key", "file.pdf", "title", "My Document Title"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().displayName()).isEqualTo("My Document Title");
    }

    @Test
    @DisplayName("retrieve uses defaultBucket when 'bucket' metadata is absent or blank")
    void retrieve_BucketMetadataAbsent_UsesDefaultBucket() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document doc = mockDoc("Content.", 0.9, Map.of("source", "file.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().bucket()).isEqualTo(DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve does not add source for a document with a blank bucket metadata value")
    void retrieve_BlankBucketMetadata_UsesDefaultBucket() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document doc = mockDoc("Content.", 0.9, Map.of("key", "file.pdf", "bucket", ""));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().bucket()).isEqualTo(DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve stops appending context when maxContextChars is reached")
    void retrieve_MaxContextCharsExhausted_SkipsRemainingDocs() {
        setupRag(true, 5, 0.4, 10);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        Document d1 = mockDoc("AAAAAAAAAA", 0.9, Map.of("source", "a.txt")); // exactly 10 chars
        Document d2 = mockDoc("BBBBBBBBBB", 0.8, Map.of("source", "b.txt")); // should not appear
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(d1, d2));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.context()).contains("AAAAAAAAAA");
        assertThat(result.context()).doesNotContain("BBBBBBBBBB");
    }

    @Test
    @DisplayName("retrieve skips source tracking for chunk with no key/source metadata (both null)")
    void retrieve_NoKeyAndNoSource_OmitsFromSources() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // Document with no "key" and no "source" in metadata -> key remains null -> skipped
        Document doc = mockDoc("Orphan content.", 0.9, java.util.Collections.emptyMap());
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).isEmpty();
        assertThat(result.context()).contains("Orphan content.");
    }

    @Test
    @DisplayName("retrieve skips source tracking when META_KEY value is a blank string (not null)")
    void retrieve_BlankMetaKeyValue_OmitsFromSources() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // META_KEY value is "" (blank, not null) -> key.isBlank() is true -> skipped
        java.util.Map<String, Object> meta = new java.util.HashMap<>();
        meta.put("key", "");
        Document doc = mockDoc("Content.", 0.9, meta);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.sources()).isEmpty();
        assertThat(result.context()).contains("Content.");
    }

    @Test
    @DisplayName("retrieve handles metadata where key value is null (stringMeta returns null)")
    void retrieve_MetaValueNull_StringMetaReturnsNull() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // metadata contains "key" but its value is null
        java.util.Map<String, Object> meta = new java.util.HashMap<>();
        meta.put("key", null);
        Document doc = mockDoc("Content.", 0.9, meta);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // "key" value is null -> stringMeta returns null -> tries SOURCE fallback -> also null -> skipped
        assertThat(result.sources()).isEmpty();
    }

    @Test
    @DisplayName("retrieve skips document whose score is below threshold in the filter lambda")
    void retrieve_ScoreBelowThreshold_DocumentFilteredOut() {
        setupRag(true, 5, 0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // score 0.5 < threshold 0.75 -> filtered out by lambda
        Document belowThreshold = mockDoc("below-threshold content", 0.5, Map.of("source", "low.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(belowThreshold));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        assertThat(result.context()).isEmpty();
        assertThat(result.sources()).isEmpty();
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve handles null metadata map (stringMeta with null meta)")
    void retrieve_NullMetadataMap_StringMetaReturnsNull() {
        setupRag(true, 5, 0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);

        // getMetadata() returns null -> stringMeta(null, ...) should return null
        Document doc = mockDoc("content", 0.9, null);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // null metadata -> key is null -> skipped from sources, but content still in context
        assertThat(result.context()).contains("content");
        assertThat(result.sources()).isEmpty();
    }

    // ------------------------------------------------------------------ helpers

    private void setupRag(boolean enabled, int topK, double threshold, int maxChars) {
        lenient().when(ragProperties.isEnabled()).thenReturn(enabled);
        lenient().when(ragProperties.getTopK()).thenReturn(topK);
        lenient().when(ragProperties.getSimilarityThreshold()).thenReturn(threshold);
        lenient().when(ragProperties.getMaxContextChars()).thenReturn(maxChars);
        lenient().when(vectorStoreResolver.resolveProviderName(any())).thenReturn("ascendai-1536");
    }

    private Document mockDoc(String text, Double score, Map<String, Object> metadata) {
        Document doc = mock(Document.class);
        lenient().when(doc.getText()).thenReturn(text);
        lenient().when(doc.getScore()).thenReturn(score);
        lenient().when(doc.getMetadata()).thenReturn(metadata);
        return doc;
    }
}
