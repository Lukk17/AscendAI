package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.service.rag.RagRetrievalResult;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
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
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RagRetrievalServiceTest {

    private static final String DEFAULT_QUERY = "What is the architecture?";
    private static final String EMBED_PROVIDER = "openai";
    private static final String DEFAULT_BUCKET = "knowledge-base";

    @Mock
    private VectorStoreResolver vectorStoreResolver;

    @Mock
    private RagProperties ragProperties;

    @Mock
    private VectorStore vectorStore;

    private RagRetrievalService ragRetrievalService;

    @BeforeEach
    void setUp() {
        ragRetrievalService = new RagRetrievalService(vectorStoreResolver, ragProperties, DEFAULT_BUCKET);
    }

    @Test
    @DisplayName("retrieve returns skipped result without touching vector store when RAG is disabled")
    void retrieve_WhenRagDisabled_ThenReturnsSkipped() {
        // given
        when(ragProperties.isEnabled()).thenReturn(false);

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
        assertThat(result.sources()).isEmpty();
        assertThat(result.retrievalRan()).isFalse();
        verifyNoInteractions(vectorStoreResolver);
    }

    @Test
    @DisplayName("retrieve returns empty context and ran=true when vector search returns no results")
    void retrieve_WhenSearchReturnsNoResults_ThenReturnsEmptyButRan() {
        // given
        setupRagProperties(0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of());

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
        assertThat(result.sources()).isEmpty();
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve returns empty context and ran=true when all scores are below the threshold")
    void retrieve_WhenAllScoresBelowThreshold_ThenReturnsEmptyButRan() {
        // given
        setupRagProperties(0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of());

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve returns empty context and ran=true when the similarity search throws")
    void retrieve_WhenSimilaritySearchFails_ThenReturnsEmptyButRan() {
        // given
        setupRagProperties(0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        when(vectorStore.similaritySearch(any(SearchRequest.class)))
                .thenThrow(new RuntimeException("Qdrant offline"));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).isEmpty();
        assertThat(result.sources()).isEmpty();
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve returns formatted RAG context when chunks score above the threshold")
    void retrieve_WhenScoreAboveThreshold_ThenReturnsFormattedContext() {
        // given
        setupRagProperties(0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc1 = createDocument("Important architecture sentence one.", 0.90, Map.of("source", "manual.pdf"));
        Document doc2 = createDocument("Secondary architecture rule.", 0.82, Map.of("source", "spec.md"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc1, doc2));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context())
                .contains("<rag_context>")
                .contains("Important architecture sentence one.")
                .contains("Secondary architecture rule.")
                .contains("</rag_context>");
        assertThat(result.retrievalRan()).isTrue();
    }

    @Test
    @DisplayName("retrieve truncates the context snippet when it exceeds maxContextChars")
    void retrieve_WhenMaxCharsExceeded_ThenTruncatesSnippet() {
        // given
        setupRagProperties(0.75, 20);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = createDocument("This is a very long string that should be cut off.", 0.90, Map.of("source", "x.md"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context()).contains("This is a very long ");
        assertThat(result.context()).doesNotContain("string that should be cut off");
    }

    @Test
    @DisplayName("retrieve deduplicates sources by bucket and key preserving first-seen order")
    void retrieve_DeduplicatesSourcesByBucketAndKey_PreservingFirstSeenOrder() {
        // given
        setupRagProperties(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document a1 = createDocument("Chunk 1 of A.", 0.91, Map.of("source", "a.pdf"));
        Document a2 = createDocument("Chunk 2 of A.", 0.85, Map.of("source", "a.pdf"));
        Document b1 = createDocument("Chunk from B.", 0.80, Map.of("source", "b.md"));
        Document a3 = createDocument("Chunk 3 of A.", 0.75, Map.of("source", "a.pdf"));
        Document c1 = createDocument("Chunk from C.", 0.70, Map.of("source", "c.txt"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(a1, a2, b1, a3, c1));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(3);
        assertThat(result.sources()).extracting(SourceRef::key)
                .containsExactly("a.pdf", "b.md", "c.txt");
        assertThat(result.sources()).allMatch(s -> DEFAULT_BUCKET.equals(s.bucket()));
    }

    @Test
    @DisplayName("retrieve uses explicit bucket/key/displayName/mimeType metadata over source fallback")
    void retrieve_PrefersExplicitMetadataOverFallbacks() {
        // given
        setupRagProperties(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = createDocument("Explicit-metadata chunk.", 0.91, Map.of(
                "bucket", "custom-bucket",
                "key", "folder/file.pdf",
                "displayName", "Custom Display.pdf",
                "mimeType", "application/pdf",
                "source", "ignored.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        SourceRef ref = result.sources().getFirst();
        assertThat(ref.bucket()).isEqualTo("custom-bucket");
        assertThat(ref.key()).isEqualTo("folder/file.pdf");
        assertThat(ref.displayName()).isEqualTo("Custom Display.pdf");
        assertThat(ref.mimeType()).isEqualTo("application/pdf");
    }

    @Test
    @DisplayName("retrieve includes orphan chunks in context but omits them from sources list")
    void retrieve_TolerateChunksMissingSourceMetadata() {
        // given
        setupRagProperties(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document withSource = createDocument("Has source.", 0.91, Map.of("source", "real.pdf"));
        Document noSource = createDocument("Orphan chunk.", 0.85, Map.of());
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(withSource, noSource));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.context())
                .contains("Has source.")
                .contains("Orphan chunk.");
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().key()).isEqualTo("real.pdf");
    }

    @Test
    @DisplayName("retrieve uses the basename of the key as the display name when no explicit displayName is set")
    void retrieve_DisplayNameFallsBackToBasenameOfKey() {
        // given
        setupRagProperties(0.4, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        Document doc = createDocument("Body.", 0.91, Map.of("source", "deep/folder/path/document.pdf"));
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        RagRetrievalResult result = ragRetrievalService.retrieve(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result.sources()).hasSize(1);
        assertThat(result.sources().getFirst().displayName()).isEqualTo("document.pdf");
    }

    private void setupRagProperties(double threshold, int maxChars) {
        lenient().when(ragProperties.isEnabled()).thenReturn(true);
        lenient().when(ragProperties.getTopK()).thenReturn(5);
        lenient().when(ragProperties.getSimilarityThreshold()).thenReturn(threshold);
        lenient().when(ragProperties.getMaxContextChars()).thenReturn(maxChars);
        lenient().when(vectorStoreResolver.resolveProviderName(any(String.class))).thenReturn("ascendai-1536");
    }

    private Document createDocument(String content, double score, Map<String, Object> metadata) {
        Document mockDoc = mock(Document.class);
        lenient().when(mockDoc.getText()).thenReturn(content);
        lenient().when(mockDoc.getScore()).thenReturn(score);
        lenient().when(mockDoc.getMetadata()).thenReturn(metadata);
        return mockDoc;
    }
}
