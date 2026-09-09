package com.lukk.ascend.ai.agent.service.ingestion;

import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.DocumentRouter;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DocumentIngestionServiceTest {

    @Mock
    private DocumentRouter documentRouter;

    @InjectMocks
    private DocumentIngestionService documentIngestionService;

    @DisplayName("process document returns empty string when file is null")
    @Test
    void processDocument_WhenFileIsNull_ThenReturnsEmptyString() {
        // given
        MultipartFile nullFile = null;

        // when
        String result = documentIngestionService.processDocument(nullFile);

        // then
        assertThat(result).isEmpty();
    }

    @DisplayName("process document returns empty string when file is empty")
    @Test
    void processDocument_WhenFileIsEmpty_ThenReturnsEmptyString() {
        // given
        MultipartFile emptyFile = new MockMultipartFile("file", new byte[0]);

        // when
        String result = documentIngestionService.processDocument(emptyFile);

        // then
        assertThat(result).isEmpty();
    }

    @DisplayName("process document routes and returns formatted string when valid file")
    @Test
    void processDocument_WhenValidFile_ThenRoutesAndReturnsFormattedString() {
        // given
        byte[] content = "Hello PDF".getBytes();
        MultipartFile file = new MockMultipartFile("file", "test.pdf", "application/pdf", content);

        Document doc1 = new Document("Line 1");
        Document doc2 = new Document("Line 2");
        when(documentRouter.routeAndProcess(eq(content), eq("test.pdf"), eq("application/pdf")))
                .thenReturn(List.of(doc1, doc2));

        // when
        String result = documentIngestionService.processDocument(file);

        // then
        assertThat(result)
                .contains("<document_context>")
                .contains("Line 1")
                .contains("Line 2")
                .contains("</document_context>");
    }

    @DisplayName("process document throws ingestion exception when io exception")
    @Test
    void processDocument_WhenIOException_ThenThrowsIngestionException() throws IOException {
        // given
        MultipartFile mockFile = mock(MultipartFile.class);
        when(mockFile.isEmpty()).thenReturn(false);
        when(mockFile.getOriginalFilename()).thenReturn("error.pdf");
        when(mockFile.getBytes()).thenThrow(new IOException("Disk read error"));

        // then
        assertThatThrownBy(() -> documentIngestionService.processDocument(mockFile))
                .isInstanceOf(IngestionException.class)
                .hasMessageContaining("Failed to read file bytes: error.pdf");
    }

    @DisplayName("process document null original filename uses document fallback")
    @Test
    void processDocument_NullOriginalFilename_UsesDocumentFallback() throws IOException {
        // given — file is not empty but getOriginalFilename() returns null
        MultipartFile mockFile = mock(MultipartFile.class);
        when(mockFile.isEmpty()).thenReturn(false);
        when(mockFile.getOriginalFilename()).thenReturn(null);
        when(mockFile.getContentType()).thenReturn("application/pdf");
        when(mockFile.getBytes()).thenReturn("content".getBytes());
        when(documentRouter.routeAndProcess(org.mockito.ArgumentMatchers.any(byte[].class), eq("document"), org.mockito.ArgumentMatchers.any()))
                .thenReturn(List.of());

        // when
        String result = documentIngestionService.processDocument(mockFile);

        // then
        assertThat(result).isNotNull();
    }
}
