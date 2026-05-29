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

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RagRetrievalServiceMetadataFallbacksTest {

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
        // given
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document nullScore = mockDoc("text", null, Map.of("source", "file.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(nullScore));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
    }

    @Test
    @DisplayName("retrieve skips null/blank text chunks when building context block")
    void retrieve_BlankTextDocument_SkippedInContext() {
        // given
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document blank = mockDoc("   ", 0.9, Map.of("source", "blank.txt"));
        Document real = mockDoc("Actual content.", 0.85, Map.of("source", "real.txt"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(blank, real));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).contains("Actual content.");
        assertThat(result.context()).doesNotContain("   ");
    }

    @Test
    @DisplayName("retrieve skips null text chunks when building context block")
    void retrieve_NullTextDocument_SkippedInContext() {
        // given
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document nullText = mockDoc(null, 0.9, Map.of("source", "nulltext.txt"));
        Document real = mockDoc("Valid text.", 0.85, Map.of("source", "real.txt"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(nullText, real));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).contains("Valid text.");
    }

    @Test
    @DisplayName("retrieve uses IngestionMetadataKeys.SOURCE fallback when 'key' metadata is absent")
    void retrieve_KeyMetadataAbsent_FallsBackToSourceMetadata() {
        // given — no "key" in metadata, only "source"
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("Content.", 0.9, Map.of("source", "docs/readme.md"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().key()).isEqualTo("docs/readme.md");
    }

    @Test
    @DisplayName("retrieve uses IngestionMetadataKeys.TITLE as displayName fallback when displayName is absent")
    void retrieve_DisplayNameAbsent_FallsBackToTitleMetadata() {
        // given — "title" is present as fallback for displayName
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("Content.", 0.9, Map.of("key", "file.pdf", "title", "My Document Title"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().displayName()).isEqualTo("My Document Title");
    }

    @Test
    @DisplayName("retrieve uses defaultBucket when 'bucket' metadata is absent or blank")
    void retrieve_BucketMetadataAbsent_UsesDefaultBucket() {
        // given
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("Content.", 0.9, Map.of("source", "file.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().bucket()).isEqualTo(DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve does not add source for a document with a blank bucket metadata value")
    void retrieve_BlankBucketMetadata_UsesDefaultBucket() {
        // given
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("Content.", 0.9, Map.of("key", "file.pdf", "bucket", ""));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().bucket()).isEqualTo(DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve stops appending context when maxContextChars is reached")
    void retrieve_MaxContextCharsExhausted_SkipsRemainingDocs() {
        // given
        setupRag(0.4, 10);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document d1 = mockDoc("AAAAAAAAAA", 0.9, Map.of("source", "a.txt")); // exactly 10 chars
        Document d2 = mockDoc("BBBBBBBBBB", 0.8, Map.of("source", "b.txt")); // should not appear
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(d1, d2));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).contains("AAAAAAAAAA");
        assertThat(result.context()).doesNotContain("BBBBBBBBBB");
    }

    @Test
    @DisplayName("retrieve skips source tracking for chunk with no key/source metadata (both null)")
    void retrieve_NoKeyAndNoSource_OmitsFromSources() {
        // given — no "key" and no "source" in metadata -> key remains null -> skipped
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("Orphan content.", 0.9, java.util.Collections.emptyMap());
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).isEmpty();
        assertThat(result.context()).contains("Orphan content.");
    }

    @Test
    @DisplayName("retrieve skips source tracking when META_KEY value is a blank string (not null)")
    void retrieve_BlankMetaKeyValue_OmitsFromSources() {
        // given — META_KEY value is "" (blank, not null) -> key.isBlank() is true -> skipped
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        java.util.Map<String, Object> meta = new java.util.HashMap<>();
        meta.put("key", "");
        Document doc = mockDoc("Content.", 0.9, meta);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).isEmpty();
        assertThat(result.context()).contains("Content.");
    }

    @Test
    @DisplayName("retrieve handles metadata where key value is null (stringMeta returns null)")
    void retrieve_MetaValueNull_StringMetaReturnsNull() {
        // given — metadata contains "key" but its value is null
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        java.util.Map<String, Object> meta = new java.util.HashMap<>();
        meta.put("key", null);
        Document doc = mockDoc("Content.", 0.9, meta);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then — "key" value is null -> stringMeta returns null -> tries SOURCE fallback -> also null -> skipped
        assertThat(result.sources()).isEmpty();
    }

    @Test
    @DisplayName("retrieve skips document whose score is below threshold in the filter lambda")
    void retrieve_ScoreBelowThreshold_DocumentFilteredOut() {
        // given — score 0.5 < threshold 0.75 -> filtered out by lambda
        setupRag(0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document belowThreshold = mockDoc("below-threshold content", 0.5, Map.of("source", "low.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(belowThreshold));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
        assertThat(result.sources()).isEmpty();
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve handles null metadata map (stringMeta with null meta)")
    void retrieve_NullMetadataMap_StringMetaReturnsNull() {
        // given — getMetadata() returns null -> stringMeta(null, ...) returns null
        setupRag(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = mockDoc("content", 0.9, null);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = service.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then — null metadata -> key is null -> skipped from sources, but content still in context
        assertThat(result.context()).contains("content");
        assertThat(result.sources()).isEmpty();
    }


    private void setupRag(double threshold, int maxChars) {
        lenient().when(ragProperties.isEnabled()).thenReturn(true);
        lenient().when(ragProperties.getTopK()).thenReturn(5);
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
