package com.lukk.ascend.ai.orchestrator.service.ingestion;

import com.lukk.ascend.ai.orchestrator.exception.DocumentRoutingException;
import com.lukk.ascend.ai.orchestrator.exception.UnsupportedFileTypeException;
import com.lukk.ascend.ai.orchestrator.service.ingestion.client.DoclingClient;
import com.lukk.ascend.ai.orchestrator.service.ingestion.client.PaddleOcrClient;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.ai.document.Document;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentRouter {

    private final IngestionService ingestionService;
    private final DoclingClient doclingClient;
    private final PaddleOcrClient paddleOcrClient;

    @Value("${app.document-router.pdf-min-text-threshold-per-page:50}")
    private int pdfMinTextThresholdPerPage;

    public List<Document> routeAndProcess(byte[] fileBytes, String filename, String contentType) {
        log.info("[DocumentRouter] Received file: {} with Content-Type: {}", filename, contentType);

        String extension = extractExtension(filename);

        return switch (extension) {
            case "md" -> routeToMarkdown(fileBytes, filename);
            case "docx", "xlsx", "pptx", "html" -> routeToDocling(fileBytes, filename);
            case "png", "jpg", "jpeg", "tiff", "bmp", "webp" -> routeToPaddleOcr(fileBytes, filename);
            case "eml", "msg", "epub", "rtf", "xml", "odt" -> routeToUnstructured(fileBytes, filename);
            case "pdf" -> routePdfPerPage(fileBytes, filename);
            default -> throw new UnsupportedFileTypeException(extension);
        };
    }

    private List<Document> routeToMarkdown(byte[] fileBytes, String filename) {
        log.info("[DocumentRouter] Routing {} to Markdown IngestionService", filename);
        try (InputStream is = new ByteArrayInputStream(fileBytes)) {
            return ingestionService.processMarkdown(is, filename);
        } catch (IOException e) {
            throw new DocumentRoutingException("Failed to process markdown: " + filename, e);
        }
    }

    private List<Document> routeToDocling(byte[] fileBytes, String filename) {
        log.info("[DocumentRouter] Routing {} to Docling", filename);
        return doclingClient.process(fileBytes, filename);
    }

    private List<Document> routeToPaddleOcr(byte[] fileBytes, String filename) {
        log.info("[DocumentRouter] Routing {} to PaddleOCR", filename);
        return paddleOcrClient.process(fileBytes, filename, null);
    }

    private List<Document> routeToUnstructured(byte[] fileBytes, String filename) {
        log.info("[DocumentRouter] Routing {} to Unstructured API", filename);
        try (InputStream is = new ByteArrayInputStream(fileBytes)) {
            return ingestionService.processUnstructured(is, filename);
        } catch (IOException e) {
            throw new DocumentRoutingException("Failed to process unstructured: " + filename, e);
        }
    }

    private List<Document> routePdfPerPage(byte[] fileBytes, String filename) {
        log.info("[DocumentRouter] Analyzing PDF per page: {}", filename);
        List<Document> allDocuments = new ArrayList<>();

        try (PDDocument pdfDocument = Loader.loadPDF(fileBytes)) {
            int totalPages = pdfDocument.getNumberOfPages();
            log.info("[DocumentRouter] PDF {} has {} pages", filename, totalPages);

            for (int pageIndex = 0; pageIndex < totalPages; pageIndex++) {
                int pageNumber = pageIndex + 1;
                String pageText = extractTextFromPage(pdfDocument, pageNumber);
                int textLength = pageText.trim().length();

                log.info("[DocumentRouter] Page {}/{} of {} has {} characters (threshold: {})",
                        pageNumber, totalPages, filename, textLength, pdfMinTextThresholdPerPage);

                byte[] singlePagePdf = extractSinglePagePdf(pdfDocument, pageIndex);
                String pageFilename = filename + "_page" + pageNumber + ".pdf";

                List<Document> pageDocuments = routeSinglePdfPage(singlePagePdf, pageFilename, textLength);
                allDocuments.addAll(pageDocuments);
            }
        } catch (IOException e) {
            throw new DocumentRoutingException("Failed to analyze PDF: " + filename, e);
        }

        return allDocuments;
    }

    private List<Document> routeSinglePdfPage(byte[] pageBytes, String pageFilename, int textLength) {
        if (textLength < pdfMinTextThresholdPerPage) {
            log.info("[DocumentRouter] {} classified as scanned/image page. Routing to PaddleOCR.", pageFilename);
            return paddleOcrClient.process(pageBytes, pageFilename, null);
        }
        log.info("[DocumentRouter] {} classified as text page. Routing to Docling.", pageFilename);
        return doclingClient.process(pageBytes, pageFilename);
    }

    private String extractTextFromPage(PDDocument document, int pageNumber) {
        try {
            PDFTextStripper stripper = new PDFTextStripper();
            stripper.setStartPage(pageNumber);
            stripper.setEndPage(pageNumber);
            String text = stripper.getText(document);
            return text != null ? text : "";
        } catch (IOException e) {
            log.warn("[DocumentRouter] Failed to extract text from page {}. Treating as image page.", pageNumber, e);
            return "";
        }
    }

    private byte[] extractSinglePagePdf(PDDocument sourceDocument, int pageIndex) throws IOException {
        try (PDDocument singlePageDoc = new PDDocument(); ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            singlePageDoc.addPage(sourceDocument.getPage(pageIndex));
            singlePageDoc.save(baos);
            return baos.toByteArray();
        }
    }

    private String extractExtension(String filename) {
        if (filename == null || !filename.contains(".")) {
            return "";
        }
        return filename.substring(filename.lastIndexOf('.') + 1).toLowerCase();
    }
}
