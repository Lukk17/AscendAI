package com.lukk.ascend.ai.agent.service.ingestion;

import com.lukk.ascend.ai.agent.exception.DocumentRoutingException;
import com.lukk.ascend.ai.agent.service.ingestion.client.DoclingClient;
import com.lukk.ascend.ai.agent.service.ingestion.client.PaddleOcrClient;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayOutputStream;
import java.io.IOException;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.when;

/**
 * Tests for DocumentRouter covering the awaitAllPagesOrThrow ExecutionException path.
 * When a page processing task (docling/paddleocr) throws a runtime exception,
 * CompletableFuture.allOf().get() throws ExecutionException and we expect
 * DocumentRoutingException to be thrown.
 */
@ExtendWith(MockitoExtension.class)
class DocumentRouterPdfExceptionTest {

    @Mock
    private IngestionService ingestionService;

    @Mock
    private DoclingClient doclingClient;

    @Mock
    private PaddleOcrClient paddleOcrClient;

    @InjectMocks
    private DocumentRouter documentRouter;

    @Test
    @DisplayName("routeAndProcess throws DocumentRoutingException when PDF page processing task fails")
    void routeAndProcess_PageProcessingTaskFails_ThrowsDocumentRoutingException() throws IOException {
        // given — set text threshold low so text-page routes to Docling
        ReflectionTestUtils.setField(documentRouter, "pdfMinTextThresholdPerPage", 0);
        ReflectionTestUtils.setField(documentRouter, "pdfParallelPages", 1);
        byte[] pdfBytes = createSinglePagePdf();
        when(doclingClient.process(any(byte[].class), anyString()))
                .thenThrow(new RuntimeException("docling service down"));

        // then
        assertThatThrownBy(() -> documentRouter.routeAndProcess(pdfBytes, "test.pdf", "application/pdf"))
                .isInstanceOf(DocumentRoutingException.class);
    }

    @Test
    @DisplayName("routeAndProcess throws DocumentRoutingException when PaddleOCR page task fails")
    void routeAndProcess_PaddleOcrPageFails_ThrowsDocumentRoutingException() throws IOException {
        // given — high threshold so page routes to PaddleOCR
        ReflectionTestUtils.setField(documentRouter, "pdfMinTextThresholdPerPage", 10_000);
        ReflectionTestUtils.setField(documentRouter, "pdfParallelPages", 1);
        byte[] pdfBytes = createSinglePagePdf();
        when(paddleOcrClient.process(any(byte[].class), anyString(), isNull()))
                .thenThrow(new RuntimeException("paddle service down"));

        // then
        assertThatThrownBy(() -> documentRouter.routeAndProcess(pdfBytes, "test.pdf", "application/pdf"))
                .isInstanceOf(DocumentRoutingException.class);
    }

    private byte[] createSinglePagePdf() throws IOException {
        try (PDDocument doc = new PDDocument(); ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            doc.addPage(new PDPage());
            doc.save(baos);
            return baos.toByteArray();
        }
    }
}
