package com.lukk.ascend.ai.orchestrator.service;

import com.lukk.ascend.ai.orchestrator.test.TestDummyBuilder;
import org.junit.jupiter.api.BeforeEach;
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

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

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
    void removeOldDocuments_ShouldDelete_WhenSourceMetadataExists() {
        // given
        String source = "test-source.md";
        Document doc = TestDummyBuilder.createDocument(source, "content");
        List<Document> documents = List.of(doc);

        // when
        documentService.removeOldDocuments(documents, vectorStore);

        // then
        verify(vectorStore, times(1)).delete(any(Filter.Expression.class));
    }

    @Test
    void removeOldDocuments_ShouldDoNothing_WhenListIsNullOrEmpty() {
        // given
        List<Document> documents = Collections.emptyList();

        // when
        documentService.removeOldDocuments(documents, vectorStore);

        // then
        verify(vectorStore, never()).delete(any(Filter.Expression.class));
    }

    @Test
    void splitDocuments_ShouldReturnChunks_WhenDocumentIsLarge() {
        // given
        // create a document content larger than chunk size (100)
        String content = "word ".repeat(200);
        Document doc = TestDummyBuilder.createDocument("source.md", content);
        List<Document> documents = List.of(doc);

        // when
        List<Document> result = documentService.splitDocuments(documents);

        // then
        assertNotNull(result);
        assertTrue(result.size() > 1);
    }

    @Test
    void splitDocuments_ShouldHandleEmptyList() {
        // given
        List<Document> documents = Collections.emptyList();

        // when
        List<Document> result = documentService.splitDocuments(documents);

        // then
        assertTrue(result.isEmpty());
    }
}
