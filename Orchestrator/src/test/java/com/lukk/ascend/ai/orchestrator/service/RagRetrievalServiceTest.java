package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.config.properties.RagProperties;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.SearchRequest;
import org.springframework.ai.vectorstore.VectorStore;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.lenient;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RagRetrievalServiceTest {

    private static final String DEFAULT_QUERY = "What is the architecture?";
    private static final String EMBED_PROVIDER = "openai";

    @Mock
    private VectorStoreResolver vectorStoreResolver;

    @Mock
    private RagProperties ragProperties;

    @Mock
    private VectorStore vectorStore;

    @InjectMocks
    private RagRetrievalService ragRetrievalService;

    @Test
    void retrieveContext_WhenRagDisabled_ThenReturnsEmptyString() {
        // given
        when(ragProperties.isEnabled()).thenReturn(false);

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result).isEmpty();
        verifyNoInteractions(vectorStoreResolver);
    }

    @Test
    void retrieveContext_WhenSearchReturnsNoResults_ThenReturnsEmptyString() {
        // given
        when(ragProperties.isEnabled()).thenReturn(true);
        when(ragProperties.getTopK()).thenReturn(5);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        when(vectorStoreResolver.resolveProviderName(EMBED_PROVIDER)).thenReturn("ascendai-1536");
        
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of());

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void retrieveContext_WhenTopScoreBelowThreshold_ThenReturnsEmptyString() {
        // given
        setupRagProperties(true, 5, 0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        
        Document doc = createDocument("Some content", 0.5); // Score below 0.75
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void retrieveContext_WhenSimilaritySearchFails_ThenReturnsEmptyString() {
        // given
        setupRagProperties(true, 5, 0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        
        when(vectorStore.similaritySearch(any(SearchRequest.class)))
                .thenThrow(new RuntimeException("Qdrant offline"));

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result).isEmpty();
    }

    @Test
    void retrieveContext_WhenScoreAboveThreshold_ThenReturnsFormattedContext() {
        // given
        setupRagProperties(true, 5, 0.75, 4000);
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        
        Document doc1 = createDocument("Important architecture sentence one.", 0.90);
        Document doc2 = createDocument("Secondary architecture rule.", 0.82);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc1, doc2));

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result)
                .contains("<rag_context>")
                .contains("Important architecture sentence one.")
                .contains("Secondary architecture rule.")
                .contains("</rag_context>");
    }

    @Test
    void retrieveContext_WhenMaxCharsExceeded_ThenTruncatesSnippet() {
        // given
        setupRagProperties(true, 5, 0.75, 20); // only allow 20 chars
        when(vectorStoreResolver.resolve(EMBED_PROVIDER)).thenReturn(vectorStore);
        
        Document doc = createDocument("This is a very long string that should be cut off.", 0.90);
        when(vectorStore.similaritySearch(any(SearchRequest.class))).thenReturn(List.of(doc));

        // when
        String result = ragRetrievalService.retrieveContext(DEFAULT_QUERY, EMBED_PROVIDER);

        // then
        assertThat(result).contains("This is a very long ");
        assertThat(result).doesNotContain("string that should be cut off");
    }

    private void setupRagProperties(boolean enabled, int topK, double threshold, int maxChars) {
        lenient().when(ragProperties.isEnabled()).thenReturn(enabled);
        lenient().when(ragProperties.getTopK()).thenReturn(topK);
        lenient().when(ragProperties.getSimilarityThreshold()).thenReturn(threshold);
        lenient().when(ragProperties.getMaxContextChars()).thenReturn(maxChars);
        lenient().when(vectorStoreResolver.resolveProviderName(any(String.class))).thenReturn("ascendai-1536");
    }
    
    private Document createDocument(String content, double score) {
        Document mockDoc = mock(Document.class);
        when(mockDoc.getText()).thenReturn(content);
        when(mockDoc.getScore()).thenReturn(score);
        return mockDoc;
    }
}
