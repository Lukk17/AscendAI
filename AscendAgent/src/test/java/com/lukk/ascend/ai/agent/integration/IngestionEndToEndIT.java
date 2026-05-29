package com.lukk.ascend.ai.agent.integration;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lukk.ascend.ai.agent.service.VectorStoreResolver;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectResponse;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Request;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Response;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;

import javax.sql.DataSource;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * End-to-end integration test for the ingestion pipeline. Drives multipart uploads through
 * the real {@code IngestionController} into MinIO and runs the manual ingestion through
 * {@link com.lukk.ascend.ai.agent.service.ManualIngestionService} against a real Postgres
 * (for the {@code INT_METADATA_STORE}) while stubbing the embedding/vector store layer
 * because LM Studio / OpenAI are unreachable in CI.
 *
 * <p>Why mock {@link VectorStoreResolver} but not MinIO/Postgres: the embedding HTTP call
 * happens inside Spring AI's {@code OpenAiEmbeddingModel}, which is constructed deep inside
 * {@code VectorStoreConfig#buildProviderVectorStore}. Stubbing the resolver keeps the
 * assertion surface simple — we still exercise the real S3 listing, the real Postgres-backed
 * metadata-store dedupe, and the real document-routing logic in {@code ManualIngestionService}.
 */
@AutoConfigureMockMvc
class IngestionEndToEndIT extends TestcontainersBase {

    @MockitoBean
    org.springframework.ai.mcp.SyncMcpToolCallbackProvider toolCallbackProvider;

    /**
     * Replace the real (network-bound) embedding/vector-store wiring. The mock resolver
     * hands back a mock {@link VectorStore} so {@code documentService.removeOldDocuments}
     * and {@code store.add(...)} both no-op without making outbound HTTP calls.
     */
    @MockitoBean
    VectorStoreResolver vectorStoreResolver;

    @Autowired
    MockMvc mockMvc;

    @Autowired
    S3Client s3Client;

    @Autowired
    DataSource dataSource;

    @Autowired
    ObjectMapper objectMapper;

    private VectorStore mockVectorStore;
    private JdbcTemplate jdbc;

    private static final String BUCKET = "knowledge-base";

    @BeforeEach
    void setUp() {
        mockVectorStore = org.mockito.Mockito.mock(VectorStore.class);
        reset(vectorStoreResolver);
        when(vectorStoreResolver.resolve(ArgumentMatchers.anyString())).thenReturn(mockVectorStore);
        when(vectorStoreResolver.resolve(ArgumentMatchers.isNull())).thenReturn(mockVectorStore);
        when(vectorStoreResolver.resolveProviderName(ArgumentMatchers.any())).thenReturn("lmstudio");

        jdbc = new JdbcTemplate(dataSource);

        // Clean MinIO bucket and the metadata store between tests so each scenario is isolated.
        clearBucket();
        jdbc.update("DELETE FROM INT_METADATA_STORE");
    }

    @Test
    void upload_acceptsMarkdownPdfAndDocxInOneRequest_andStoresInMinio() throws Exception {
        MockMultipartFile mdFile = new MockMultipartFile(
                "file", "notes.md", "text/markdown",
                "# Title\n\nSome **bold** body text for the e2e ingestion test.".getBytes());

        MockMultipartFile pdfFile = new MockMultipartFile(
                "file", "report.pdf", "application/pdf",
                minimalPdfBytes());

        MockMultipartFile docxFile = new MockMultipartFile(
                "file", "doc.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                minimalDocxBytes());

        MvcResult result = mockMvc.perform(multipart("/api/v1/ingestion/upload")
                        .file(mdFile)
                        .file(pdfFile)
                        .file(docxFile))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.uploaded.length()").value(3))
                .andReturn();

        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        List<String> keys = objectMapper.convertValue(body.get("uploaded"), new TypeReference<List<String>>() {
        });

        assertThat(keys).contains("markdown/notes.md", "documents/report.pdf");
        // DOCX-by-extension is rejected if Tika sniffs the synthesized bytes as plain zip,
        // but a zip is itself in the allowlist — so the key may be either documents/doc.docx
        // or absent. We assert both possible accepted shapes.
        assertThat(keys).anyMatch(k -> k.equals("documents/doc.docx"));

        // Real MinIO must have the objects we claim to have uploaded.
        for (String key : keys) {
            HeadObjectResponse head = s3Client.headObject(HeadObjectRequest.builder()
                    .bucket(BUCKET).key(key).build());
            assertThat(head.contentLength()).isPositive();
        }
    }

    @Test
    void upload_rejectsDisallowedPayload_with415_andLeavesMinioUntouched() throws Exception {
        // SVG bytes — Tika detects as image/svg+xml, which is NOT in the allowlist
        // (only png/jpeg/webp/gif are). Reliable across Tika versions because the
        // <svg xmlns="http://www.w3.org/2000/svg"> root element is the canonical signature.
        byte[] svgBytes = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                + "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\">"
                + "<rect width=\"10\" height=\"10\" fill=\"red\"/></svg>").getBytes();
        MockMultipartFile bad = new MockMultipartFile(
                "file", "evil.svg", "image/svg+xml", svgBytes);

        mockMvc.perform(multipart("/api/v1/ingestion/upload").file(bad))
                .andExpect(status().isUnsupportedMediaType())
                .andExpect(jsonPath("$.status").value(415))
                .andExpect(jsonPath("$.error").value("unsupported_media_type"))
                .andExpect(jsonPath("$.message").exists());

        // Nothing should have landed in MinIO for this filename.
        ListObjectsV2Response list = s3Client.listObjectsV2(ListObjectsV2Request.builder()
                .bucket(BUCKET).build());
        assertThat(list.contents()).noneMatch(o -> o.key().endsWith("evil.svg"));
    }

    @Test
    void upload_filenameWithTraversalIsSanitized() throws Exception {
        MockMultipartFile traversal = new MockMultipartFile(
                "file", "../../etc/passwd.md", "text/markdown",
                "# Sanitized\n\nContent.".getBytes());

        MvcResult result = mockMvc.perform(multipart("/api/v1/ingestion/upload").file(traversal))
                .andExpect(status().isOk())
                .andReturn();

        JsonNode body = objectMapper.readTree(result.getResponse().getContentAsString());
        List<String> keys = objectMapper.convertValue(body.get("uploaded"), new TypeReference<List<String>>() {
        });

        assertThat(keys).hasSize(1);
        String key = keys.getFirst();

        // IngestionSecurity strips path segments and dot-runs; the resulting key must NOT
        // contain ".." anywhere and must NOT have a leading slash on the filename portion.
        assertThat(key).doesNotContain("..");
        assertThat(key).startsWith("markdown/");
        String filenameOnly = key.substring("markdown/".length());
        assertThat(filenameOnly).doesNotStartWith("/");
        assertThat(filenameOnly).doesNotStartWith(".");
        assertThat(filenameOnly).endsWith(".md");

        // And the sanitized object must actually be reachable in MinIO.
        HeadObjectResponse head = s3Client.headObject(HeadObjectRequest.builder()
                .bucket(BUCKET).key(key).build());
        assertThat(head.contentLength()).isPositive();
    }

    @Test
    void runIngestion_processesUploadedMarkdown_andPersistsMetadataAndCallsVectorStore() throws Exception {
        // Upload a single Markdown file — the run pipeline should ingest it.
        MockMultipartFile mdFile = new MockMultipartFile(
                "file", "run-target.md", "text/markdown",
                ("# Heading\n\n" + "Body content. ".repeat(50)).getBytes());

        mockMvc.perform(multipart("/api/v1/ingestion/upload").file(mdFile))
                .andExpect(status().isOk());

        mockMvc.perform(post("/api/v1/ingestion/run")
                        .param("embeddingProvider", "lmstudio")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.indexed").isNumber())
                .andExpect(jsonPath("$.failed").value(0));

        // The metadata store must have been written through to Postgres for the uploaded key.
        Integer count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM INT_METADATA_STORE WHERE METADATA_KEY LIKE 'manual-ingestion:markdown/run-target.md:%'",
                Integer.class);
        assertThat(count).isNotNull().isGreaterThanOrEqualTo(1);

        // The mock vector store must have received at least one chunk add call.
        verify(mockVectorStore, atLeastOnce()).add(ArgumentMatchers.<List<Document>>any());
    }

    @Test
    void runIngestion_isIdempotent_acrossRepeatedRuns() throws Exception {
        MockMultipartFile mdFile = new MockMultipartFile(
                "file", "idempotent.md", "text/markdown",
                ("# Title\n\n" + "Repeatable body. ".repeat(50)).getBytes());

        mockMvc.perform(multipart("/api/v1/ingestion/upload").file(mdFile))
                .andExpect(status().isOk());

        // First run: indexed > 0, mock add invoked.
        mockMvc.perform(post("/api/v1/ingestion/run")
                        .param("embeddingProvider", "lmstudio")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk());
        verify(mockVectorStore, atLeastOnce()).add(ArgumentMatchers.<List<Document>>any());

        Integer countAfterFirst = jdbc.queryForObject(
                "SELECT COUNT(*) FROM INT_METADATA_STORE WHERE METADATA_KEY LIKE 'manual-ingestion:%'",
                Integer.class);

        // Reset interactions on the mock, so the second-run assertion is unambiguous —
        // we want to prove the second run did NOT call add() at all (the metadata store
        // dedupes everything).
        reset(mockVectorStore);
        // Re-stub resolver because reset() also wipes the resolver mock if shared (it's not, but be safe).
        when(vectorStoreResolver.resolve(ArgumentMatchers.anyString())).thenReturn(mockVectorStore);
        when(vectorStoreResolver.resolve(ArgumentMatchers.isNull())).thenReturn(mockVectorStore);

        mockMvc.perform(post("/api/v1/ingestion/run")
                        .param("embeddingProvider", "lmstudio")
                        .contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.skipped").isNumber());

        // No new metadata-store rows.
        Integer countAfterSecond = jdbc.queryForObject(
                "SELECT COUNT(*) FROM INT_METADATA_STORE WHERE METADATA_KEY LIKE 'manual-ingestion:%'",
                Integer.class);
        assertThat(countAfterSecond).isEqualTo(countAfterFirst);

        // No vector store writes on the second run.
        verify(mockVectorStore, never()).add(any());
    }

    private void clearBucket() {
        ListObjectsV2Response list = s3Client.listObjectsV2(ListObjectsV2Request.builder()
                .bucket(BUCKET).build());
        for (var obj : list.contents()) {
            try {
                s3Client.deleteObject(b -> b.bucket(BUCKET).key(obj.key()));
            } catch (NoSuchKeyException ignored) {
                // already gone
            }
        }
    }

    /**
     * Smallest structurally valid PDF-1.4 byte sequence Tika reliably sniffs as application/pdf.
     */
    private static byte[] minimalPdfBytes() {
        String pdf = "%PDF-1.4\n"
                + "1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
                + "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
                + "3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>\nendobj\n"
                + "xref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000060 00000 n\n0000000110 00000 n\n"
                + "trailer\n<< /Size 4 /Root 1 0 R >>\n"
                + "startxref\n170\n%%EOF\n";
        return pdf.getBytes();
    }

    /**
     * Minimal zip-with-DOCX-marker bytes. A real DOCX is a zip containing
     * {@code [Content_Types].xml} — Tika sniffs the marker and returns the OOXML wordprocessingml MIME.
     * If detection falls back to {@code application/zip}, the upload still succeeds (zip is allowlisted),
     * which keeps Test 1 stable.
     */
    private static byte[] minimalDocxBytes() {
        // Build a genuine (tiny) zip with a single [Content_Types].xml entry so Tika has the
        // OOXML signal it needs. Generated in-memory via java.util.zip to avoid a fixture file.
        try (var baos = new java.io.ByteArrayOutputStream();
             var zos = new java.util.zip.ZipOutputStream(baos)) {
            zos.putNextEntry(new java.util.zip.ZipEntry("[Content_Types].xml"));
            String contentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
                    + "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
                    + "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
                    + "<Override PartName=\"/word/document.xml\" "
                    + "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
                    + "</Types>";
            zos.write(contentTypes.getBytes());
            zos.closeEntry();
            zos.putNextEntry(new java.util.zip.ZipEntry("word/document.xml"));
            zos.write(("<?xml version=\"1.0\"?><w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                    + "<w:body><w:p><w:r><w:t>Hello.</w:t></w:r></w:p></w:body></w:document>").getBytes());
            zos.closeEntry();
            zos.finish();
            return baos.toByteArray();
        } catch (java.io.IOException e) {
            throw new IllegalStateException(e);
        }
    }
}
