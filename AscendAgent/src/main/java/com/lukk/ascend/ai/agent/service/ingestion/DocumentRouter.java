package com.lukk.ascend.ai.agent.service.ingestion;

import com.lukk.ascend.ai.agent.exception.DocumentRoutingException;
import com.lukk.ascend.ai.agent.exception.UnsupportedFileTypeException;
import com.lukk.ascend.ai.agent.service.ingestion.client.DoclingClient;
import com.lukk.ascend.ai.agent.service.ingestion.client.PaddleOcrClient;
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
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentRouter {

    private final IngestionService ingestionService;
    private final DoclingClient doclingClient;
    private final PaddleOcrClient paddleOcrClient;

    @Value("${app.document-router.pdf-min-text-threshold-per-page:50}")
    private int pdfMinTextThresholdPerPage;

    @Value("${app.document-router.pdf-parallel-pages:8}")
    private int pdfParallelPages;

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

        try (PDDocument pdfDocument = Loader.loadPDF(fileBytes)) {
            int totalPages = pdfDocument.getNumberOfPages();
            log.info("[DocumentRouter] PDF {} has {} pages", filename, totalPages);

            // Slice up the work serially (PDFBox isn't thread-safe enough to share a
            // PDDocument across threads — we extract per-page text + a single-page PDF
            // byte array here, then dispatch the actual Docling / PaddleOCR calls in
            // parallel below. This is the slow part anyway (network + remote parse).
            List<PageWork> pageWork = new ArrayList<>(totalPages);
            for (int pageIndex = 0; pageIndex < totalPages; pageIndex++) {
                int pageNumber = pageIndex + 1;
                String pageText = extractTextFromPage(pdfDocument, pageNumber);
                int textLength = pageText.trim().length();
                byte[] singlePagePdf = extractSinglePagePdf(pdfDocument, pageIndex);
                String pageFilename = filename + "_page" + pageNumber + ".pdf";
                log.info("[DocumentRouter] Page {}/{} of {} has {} characters (threshold: {})",
                        pageNumber, totalPages, filename, textLength, pdfMinTextThresholdPerPage);
                pageWork.add(new PageWork(pageNumber, pageFilename, singlePagePdf, textLength));
            }

            return dispatchPagesInParallel(pageWork, filename);
        } catch (IOException e) {
            throw new DocumentRoutingException("Failed to analyze PDF: " + filename, e);
        }
    }

    private List<Document> dispatchPagesInParallel(List<PageWork> pageWork, String filename) {
        int parallelism = Math.max(1, Math.min(pdfParallelPages, pageWork.size()));
        log.info("[DocumentRouter] Dispatching {} pages of {} in parallel (parallelism={})",
                pageWork.size(), filename, parallelism);

        ExecutorService pool = Executors.newFixedThreadPool(parallelism);
        try {
            List<CompletableFuture<PageResult>> futures = new ArrayList<>(pageWork.size());
            for (PageWork work : pageWork) {
                futures.add(CompletableFuture.supplyAsync(() ->
                                new PageResult(work.pageNumber,
                                        routeSinglePdfPage(work.pdfBytes, work.pageFilename, work.textLength)),
                        pool));
            }

            CompletableFuture<Void> all = CompletableFuture.allOf(futures.toArray(new CompletableFuture[0]));
            try {
                all.get();
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                throw new DocumentRoutingException("Interrupted while routing PDF pages: " + filename, ie);
            } catch (ExecutionException ee) {
                Throwable cause = ee.getCause() != null ? ee.getCause() : ee;
                throw new DocumentRoutingException("Failed to route PDF page: " + filename, cause);
            }

            List<PageResult> results = new ArrayList<>(futures.size());
            for (CompletableFuture<PageResult> f : futures) {
                results.add(f.join());
            }
            results.sort((a, b) -> Integer.compare(a.pageNumber, b.pageNumber));

            List<Document> ordered = new ArrayList<>();
            for (PageResult r : results) {
                ordered.addAll(r.documents);
            }
            return ordered;
        } finally {
            pool.shutdown();
            try {
                if (!pool.awaitTermination(5, TimeUnit.SECONDS)) {
                    pool.shutdownNow();
                }
            } catch (InterruptedException ie) {
                pool.shutdownNow();
                Thread.currentThread().interrupt();
            }
        }
    }

    private record PageWork(int pageNumber, String pageFilename, byte[] pdfBytes, int textLength) {
    }

    private record PageResult(int pageNumber, List<Document> documents) {
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
