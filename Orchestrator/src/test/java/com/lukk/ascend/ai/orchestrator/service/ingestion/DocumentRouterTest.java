package com.lukk.ascend.ai.orchestrator.service.ingestion;

import com.lukk.ascend.ai.orchestrator.exception.DocumentRoutingException;
import com.lukk.ascend.ai.orchestrator.exception.UnsupportedFileTypeException;
import com.lukk.ascend.ai.orchestrator.service.ingestion.client.DoclingClient;
import com.lukk.ascend.ai.orchestrator.service.ingestion.client.PaddleOcrClient;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.PDPageContentStream;
import org.apache.pdfbox.pdmodel.font.PDType1Font;
import org.apache.pdfbox.pdmodel.font.Standard14Fonts;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class DocumentRouterTest {

    private static final int TEXT_THRESHOLD = 50;

    @Mock
    private IngestionService ingestionService;

    @Mock
    private DoclingClient doclingClient;

    @Mock
    private PaddleOcrClient paddleOcrClient;

    @InjectMocks
    private DocumentRouter documentRouter;

    @AfterEach
    void tearDown() {
        verifyNoMoreInteractions(ingestionService, doclingClient, paddleOcrClient);
    }

    @Test
    void routeAndProcess_WhenMarkdownFile_ThenRouteToIngestionService() {
        byte[] bytes = "test".getBytes();
        String filename = "test.md";
        Document mockDoc = new Document("markdown text");
        when(ingestionService.processMarkdown(any(InputStream.class), eq(filename)))
                .thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(bytes, filename, "text/markdown");

        assertThat(result).containsExactly(mockDoc);
        verify(ingestionService).processMarkdown(any(InputStream.class), eq(filename));
    }

    @ParameterizedTest
    @ValueSource(strings = {"docx", "xlsx", "pptx", "html"})
    void routeAndProcess_WhenDoclingFileType_ThenRouteToDocling(String extension) {
        byte[] bytes = "test".getBytes();
        String filename = "file." + extension;
        Document mockDoc = new Document("docling text");
        when(doclingClient.process(bytes, filename)).thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(bytes, filename, "application/octet-stream");

        assertThat(result).containsExactly(mockDoc);
        verify(doclingClient).process(bytes, filename);
    }

    @ParameterizedTest
    @ValueSource(strings = {"png", "jpg", "jpeg", "tiff", "bmp", "webp"})
    void routeAndProcess_WhenImageFile_ThenRouteToPaddleOcr(String extension) {
        byte[] bytes = "image_bytes".getBytes();
        String filename = "scan." + extension;
        Document mockDoc = new Document("ocr text");
        when(paddleOcrClient.process(bytes, filename, null)).thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(bytes, filename, "image/" + extension);

        assertThat(result).containsExactly(mockDoc);
        verify(paddleOcrClient).process(bytes, filename, null);
    }

    @ParameterizedTest
    @ValueSource(strings = {"eml", "msg", "epub", "rtf", "xml", "odt"})
    void routeAndProcess_WhenUnstructuredFileType_ThenRouteToUnstructured(String extension) {
        byte[] bytes = "content".getBytes();
        String filename = "file." + extension;
        Document mockDoc = new Document("unstructured text");
        when(ingestionService.processUnstructured(any(InputStream.class), eq(filename)))
                .thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(bytes, filename, "application/octet-stream");

        assertThat(result).containsExactly(mockDoc);
        verify(ingestionService).processUnstructured(any(InputStream.class), eq(filename));
    }

    @Test
    void routeAndProcess_WhenUnsupportedExtension_ThenThrowUnsupportedFileTypeException() {
        byte[] bytes = "executable".getBytes();
        String filename = "malware.exe";

        assertThatThrownBy(() -> documentRouter.routeAndProcess(bytes, filename, "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class)
                .hasMessageContaining("exe");
    }

    @Test
    void routeAndProcess_WhenNullFilename_ThenThrowUnsupportedFileTypeException() {
        byte[] bytes = "content".getBytes();

        assertThatThrownBy(() -> documentRouter.routeAndProcess(bytes, null, "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class);
    }

    @Test
    void routeAndProcess_WhenFilenameWithoutExtension_ThenThrowUnsupportedFileTypeException() {
        byte[] bytes = "content".getBytes();

        assertThatThrownBy(() -> documentRouter.routeAndProcess(bytes, "noextension", "application/octet-stream"))
                .isInstanceOf(UnsupportedFileTypeException.class);
    }

    @Test
    void routeAndProcess_WhenTextPdf_ThenRouteToDocling() throws IOException {
        setThreshold(TEXT_THRESHOLD);
        byte[] pdfBytes = createTextPdf(generateLongText());
        String filename = "document.pdf";
        Document mockDoc = new Document("pdf text");
        when(doclingClient.process(any(byte[].class), eq(filename + "_page1.pdf"))).thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(pdfBytes, filename, "application/pdf");

        assertThat(result).containsExactly(mockDoc);
        verify(doclingClient).process(any(byte[].class), eq(filename + "_page1.pdf"));
    }

    @Test
    void routeAndProcess_WhenScanPdf_ThenRouteToPaddleOcr() throws IOException {
        setThreshold(TEXT_THRESHOLD);
        byte[] pdfBytes = createTextPdf("Short");
        String filename = "scan.pdf";
        Document mockDoc = new Document("ocr text");
        when(paddleOcrClient.process(any(byte[].class), eq(filename + "_page1.pdf"), isNull()))
                .thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(pdfBytes, filename, "application/pdf");

        assertThat(result).containsExactly(mockDoc);
        verify(paddleOcrClient).process(any(byte[].class), eq(filename + "_page1.pdf"), isNull());
    }

    @Test
    void routeAndProcess_WhenMixedPdf_ThenRoutePagesSeparately() throws IOException {
        setThreshold(TEXT_THRESHOLD);
        byte[] pdfBytes = createMixedPdf(generateLongText(), "S");
        String filename = "mixed.pdf";
        Document doclingDoc = new Document("text page");
        Document ocrDoc = new Document("image page");
        when(doclingClient.process(any(byte[].class), eq(filename + "_page1.pdf")))
                .thenReturn(List.of(doclingDoc));
        when(paddleOcrClient.process(any(byte[].class), eq(filename + "_page2.pdf"), isNull()))
                .thenReturn(List.of(ocrDoc));

        List<Document> result = documentRouter.routeAndProcess(pdfBytes, filename, "application/pdf");

        assertThat(result).hasSize(2);
        assertThat(result).containsExactly(doclingDoc, ocrDoc);
        verify(doclingClient).process(any(byte[].class), eq(filename + "_page1.pdf"));
        verify(paddleOcrClient).process(any(byte[].class), eq(filename + "_page2.pdf"), isNull());
    }

    @Test
    void routeAndProcess_WhenMultiPageAllText_ThenAllPagesToDocling() throws IOException {
        setThreshold(TEXT_THRESHOLD);
        byte[] pdfBytes = createMixedPdf(generateLongText(), generateLongText());
        String filename = "alltext.pdf";
        Document doc1 = new Document("page1 text");
        Document doc2 = new Document("page2 text");
        when(doclingClient.process(any(byte[].class), eq(filename + "_page1.pdf")))
                .thenReturn(List.of(doc1));
        when(doclingClient.process(any(byte[].class), eq(filename + "_page2.pdf")))
                .thenReturn(List.of(doc2));

        List<Document> result = documentRouter.routeAndProcess(pdfBytes, filename, "application/pdf");

        assertThat(result).hasSize(2).containsExactly(doc1, doc2);
        verify(doclingClient).process(any(byte[].class), eq(filename + "_page1.pdf"));
        verify(doclingClient).process(any(byte[].class), eq(filename + "_page2.pdf"));
    }

    @Test
    void routeAndProcess_WhenInvalidPdfBytes_ThenThrowDocumentRoutingException() {
        setThreshold(TEXT_THRESHOLD);
        byte[] invalidPdfBytes = "not_a_real_pdf".getBytes();
        String filename = "broken.pdf";

        assertThatThrownBy(() -> documentRouter.routeAndProcess(invalidPdfBytes, filename, "application/pdf"))
                .isInstanceOf(DocumentRoutingException.class)
                .hasMessageContaining(filename);
    }

    @Test
    void routeAndProcess_WhenSinglePageBlankPdf_ThenRouteToPaddleOcr() throws IOException {
        setThreshold(TEXT_THRESHOLD);
        byte[] pdfBytes = createBlankPdf();
        String filename = "blank.pdf";
        Document mockDoc = new Document("ocr result");
        when(paddleOcrClient.process(any(byte[].class), eq(filename + "_page1.pdf"), isNull()))
                .thenReturn(List.of(mockDoc));

        List<Document> result = documentRouter.routeAndProcess(pdfBytes, filename, "application/pdf");

        assertThat(result).containsExactly(mockDoc);
        verify(paddleOcrClient).process(any(byte[].class), eq(filename + "_page1.pdf"), isNull());
    }

    private void setThreshold(int threshold) {
        ReflectionTestUtils.setField(documentRouter, "pdfMinTextThresholdPerPage", threshold);
    }

    private String generateLongText() {
        return "This is a text pdf with sufficient length to pass the threshold. " +
                "We need at least fifty characters so I will keep typing until it is long enough.";
    }

    private byte[] createTextPdf(String text) throws IOException {
        try (PDDocument document = new PDDocument(); ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            PDPage page = new PDPage();
            document.addPage(page);
            writeTextToPage(document, page, text);
            document.save(baos);
            return baos.toByteArray();
        }
    }

    private byte[] createMixedPdf(String textPage1, String textPage2) throws IOException {
        try (PDDocument document = new PDDocument(); ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            PDPage page1 = new PDPage();
            document.addPage(page1);
            writeTextToPage(document, page1, textPage1);

            PDPage page2 = new PDPage();
            document.addPage(page2);
            writeTextToPage(document, page2, textPage2);

            document.save(baos);
            return baos.toByteArray();
        }
    }

    private byte[] createBlankPdf() throws IOException {
        try (PDDocument document = new PDDocument(); ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            document.addPage(new PDPage());
            document.save(baos);
            return baos.toByteArray();
        }
    }

    private void writeTextToPage(PDDocument document, PDPage page, String text) throws IOException {
        try (PDPageContentStream contentStream = new PDPageContentStream(document, page)) {
            contentStream.beginText();
            contentStream.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA), 12);
            contentStream.newLineAtOffset(100, 700);
            contentStream.showText(text);
            contentStream.endText();
        }
    }
}
