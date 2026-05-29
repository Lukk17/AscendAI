package com.lukk.ascend.ai.agent.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.Filter;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class DocumentServiceTest {

    @Mock
    private VectorStore vectorStore;

    @InjectMocks
    private DocumentService documentService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(documentService, "tokenSplitterChunkSize", 100);
        ReflectionTestUtils.setField(documentService, "minChunkSizeChars", 10);
        ReflectionTestUtils.setField(documentService, "minChunkLengthToEmbed", 5);
        ReflectionTestUtils.setField(documentService, "maxNumChunks", 100);
        ReflectionTestUtils.setField(documentService, "keepSeparator", true);
    }

    @Test
    @DisplayName("removeOldDocuments deletes by filter when source metadata exists")
    void removeOldDocuments_ShouldDelete_WhenSourceMetadataExists() {
        // given
        Document doc = documentWithSource("test-source.md", "content");

        // when
        documentService.removeOldDocuments(List.of(doc), vectorStore);

        // then
        verify(vectorStore, times(1)).delete(any(Filter.Expression.class));
    }

    @Test
    @DisplayName("removeOldDocuments does nothing when the document list is empty")
    void removeOldDocuments_ShouldDoNothing_WhenListIsNullOrEmpty() {
        // when
        documentService.removeOldDocuments(Collections.emptyList(), vectorStore);

        // then
        verify(vectorStore, never()).delete(any(Filter.Expression.class));
    }

    @Test
    @DisplayName("splitDocuments returns multiple chunks when content exceeds chunk size")
    void splitDocuments_ShouldReturnChunks_WhenDocumentIsLarge() {
        // given
        String content = "word ".repeat(200);
        Document doc = documentWithSource("source.md", content);

        // when
        List<Document> result = documentService.splitDocuments(List.of(doc));

        // then
        assertThat(result).hasSizeGreaterThan(1);
    }

    @Test
    @DisplayName("splitDocuments returns empty list when input is empty")
    void splitDocuments_ShouldHandleEmptyList() {
        // when
        List<Document> result = documentService.splitDocuments(Collections.emptyList());

        // then
        assertThat(result).isEmpty();
    }

    @Test
    @DisplayName("removeOldDocuments does nothing when the documents list is null")
    void removeOldDocuments_NullList_DoesNothing() {
        documentService.removeOldDocuments(null, vectorStore);

        verify(vectorStore, never()).delete(any(Filter.Expression.class));
    }

    @Test
    @DisplayName("removeOldDocuments does not delete when source metadata value is not a String")
    void removeOldDocuments_SourceNotString_DoesNotCallDelete() {
        // given — source is an Integer; instanceof String fails
        Document doc = new Document("text", Map.of("source", 42));

        // when
        documentService.removeOldDocuments(List.of(doc), vectorStore);

        // then
        verify(vectorStore, never()).delete(any(Filter.Expression.class));
    }

    private static Document documentWithSource(String source, String content) {
        return new Document(content, Map.of("source", source, "title", source));
    }
}
