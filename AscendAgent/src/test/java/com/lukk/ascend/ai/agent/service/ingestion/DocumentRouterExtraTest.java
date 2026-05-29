package com.lukk.ascend.ai.agent.service.ingestion;

import com.lukk.ascend.ai.agent.exception.UnsupportedFileTypeException;
import com.lukk.ascend.ai.agent.service.ingestion.client.DoclingClient;
import com.lukk.ascend.ai.agent.service.ingestion.client.PaddleOcrClient;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;

import java.io.InputStream;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for DocumentRouter: image routing to PaddleOCR,
 * legacy unstructured-type extensions, null/no-dot filename, markdown routing.
 */
@ExtendWith(MockitoExtension.class)
class DocumentRouterExtraTest {

    @Mock
    private IngestionService ingestionService;

    @Mock
    private DoclingClient doclingClient;

    @Mock
    private PaddleOcrClient paddleOcrClient;

    @InjectMocks
    private DocumentRouter documentRouter;

    @Test
    @DisplayName("routeAndProcess routes .png file to PaddleOCR")
    void routeAndProcess_PngExtension_RoutesToPaddleOcr() {
        // given
        when(paddleOcrClient.process(any(byte[].class), anyString(), isNull()))
                .thenReturn(List.of(new Document("ocr text")));

        // when
        List<Document> docs = documentRouter.routeAndProcess("img".getBytes(), "photo.png", "image/png");

        // then
        verify(paddleOcrClient).process(any(byte[].class), eq("photo.png"), isNull());
        assertThat(docs).hasSize(1);
    }

    @Test
    @DisplayName("routeAndProcess routes .jpg file to PaddleOCR")
    void routeAndProcess_JpgExtension_RoutesToPaddleOcr() {
        when(paddleOcrClient.process(any(), anyString(), isNull())).thenReturn(List.of(new Document("text")));

        documentRouter.routeAndProcess("img".getBytes(), "scan.jpg", "image/jpeg");

        verify(paddleOcrClient).process(any(), eq("scan.jpg"), isNull());
    }

    @Test
    @DisplayName("routeAndProcess routes .eml file to IngestionService.processUnstructured")
    void routeAndProcess_EmlExtension_RoutesToUnstructured() {
        when(ingestionService.processUnstructured(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("eml text")));

        List<Document> docs = documentRouter.routeAndProcess("content".getBytes(), "email.eml", "message/rfc822");

        verify(ingestionService).processUnstructured(any(InputStream.class), eq("email.eml"));
        assertThat(docs).hasSize(1);
    }

    @Test
    @DisplayName("routeAndProcess routes .rtf file to IngestionService.processUnstructured")
    void routeAndProcess_RtfExtension_RoutesToUnstructured() {
        when(ingestionService.processUnstructured(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("rtf text")));

        documentRouter.routeAndProcess("content".getBytes(), "doc.rtf", "application/rtf");

        verify(ingestionService).processUnstructured(any(), eq("doc.rtf"));
    }

    @Test
    @DisplayName("routeAndProcess routes .md file to IngestionService.processMarkdown")
    void routeAndProcess_MdExtension_RoutesToMarkdown() {
        when(ingestionService.processMarkdown(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("md text")));

        documentRouter.routeAndProcess("# Title".getBytes(), "readme.md", "text/markdown");

        verify(ingestionService).processMarkdown(any(InputStream.class), eq("readme.md"));
    }

    @Test
    @DisplayName("routeAndProcess routes .docx file to DoclingClient")
    void routeAndProcess_DocxExtension_RoutesToDocling() {
        when(doclingClient.process(any(), anyString())).thenReturn(List.of(new Document("docx text")));

        documentRouter.routeAndProcess("content".getBytes(), "contract.docx", "application/vnd.openxmlformats");

        verify(doclingClient).process(any(), eq("contract.docx"));
    }

    @Test
    @DisplayName("routeAndProcess throws UnsupportedFileTypeException for unknown extension")
    void routeAndProcess_UnknownExtension_ThrowsUnsupportedFileTypeException() {
        assertThatThrownBy(() -> documentRouter.routeAndProcess("data".getBytes(), "file.xyz", "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class);
    }

    @Test
    @DisplayName("routeAndProcess throws UnsupportedFileTypeException when filename has no extension")
    void routeAndProcess_NoDotInFilename_ThrowsUnsupportedFileTypeException() {
        assertThatThrownBy(() -> documentRouter.routeAndProcess("data".getBytes(), "noextension", "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class);
    }

    @Test
    @DisplayName("routeAndProcess throws UnsupportedFileTypeException when filename is null")
    void routeAndProcess_NullFilename_ThrowsUnsupportedFileTypeException() {
        assertThatThrownBy(() -> documentRouter.routeAndProcess("data".getBytes(), null, "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class);
    }
}
