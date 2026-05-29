package com.lukk.ascend.ai.agent.service;

import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.test.util.ReflectionTestUtils;
import software.amazon.awssdk.core.ResponseInputStream;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Request;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Response;
import software.amazon.awssdk.services.s3.model.S3Object;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ManualIngestionServiceTest {

    @Mock
    private S3Client s3Client;

    @Mock
    private ConcurrentMetadataStore metadataStore;

    @Mock
    private IngestionService ingestionService;

    @Mock
    private DocumentService documentService;

    @Mock
    private VectorStoreResolver vectorStoreResolver;

    @Mock
    private VectorStore vectorStore;

    @InjectMocks
    private ManualIngestionService manualIngestionService;

    @BeforeEach
    void setupGlobalFields() {
        ReflectionTestUtils.setField(manualIngestionService, "bucket", "test-bucket");
        ReflectionTestUtils.setField(manualIngestionService, "markdownFolder", "markdown/");
        ReflectionTestUtils.setField(manualIngestionService, "documentsFolder", "documents/");
    }

    @Test
    @DisplayName("run returns all-zero result when no objects are found in the bucket")
    void run_WhenNoObjectsFound_ThenReturnsZeros() {
        // given
        ListObjectsV2Response emptyResponse = ListObjectsV2Response.builder().contents(List.of()).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(emptyResponse);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isZero();
        assertThat(result.skipped).isZero();
        assertThat(result.failed).isZero();
    }

    @Test
    @DisplayName("run skips objects that are not in the configured ingestion folders")
    void run_WhenObjectExcludedByFolder_ThenSkipsObject() {
        // given
        S3Object invalidObject = S3Object.builder().key("irrelevant/file.txt").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(invalidObject)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.skipped).isEqualTo(1);
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run skips objects that are already indexed according to the metadata store")
    void run_WhenObjectAlreadyIndexed_ThenSkipsObject() {
        // given
        S3Object validObject = S3Object.builder().key("markdown/file.md").eTag("v1").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(validObject)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn("EXISTING_TIMESTAMP");

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.skipped).isEqualTo(1);
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run ingests a valid markdown object and indexes all document chunks")
    void run_WhenValidMarkdownObject_ThenIngestsProperly() {
        // given
        S3Object obj = S3Object.builder().key("markdown/test.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);

        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);

        Document processedDoc = new Document("MD Text");
        when(ingestionService.processMarkdown(any(), eq("markdown/test.md"))).thenReturn(List.of(processedDoc));


        Document chunk1 = new Document("Chunk 1");
        Document chunk2 = new Document("Chunk 2");
        when(documentService.splitDocuments(any())).thenReturn(List.of(chunk1, chunk2));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.of("markdown/"), "openai");

        // then
        assertThat(result.indexed).isEqualTo(2);
        assertThat(result.skipped).isZero();

        verify(documentService).removeOldDocuments(any(), eq(vectorStore));
        verify(vectorStore).add(List.of(chunk1));
        verify(vectorStore).add(List.of(chunk2));
    }

    @Test
    @DisplayName("run delegates PDF processing to the unstructured service")
    void run_WhenValidPdfObject_ThenDelegatesToUnstructured() {
        // given — No etag, no lastModified tests unknown fallback
        S3Object obj = S3Object.builder().key("documents/report.pdf").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(enforceMetaKey("manual-ingestion:documents/report.pdf:unknown"), anyString())).thenReturn(null);

        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);

        Document processedDoc = new Document("PDF Text");
        when(ingestionService.processUnstructured(any(), eq("documents/report.pdf"))).thenReturn(List.of(processedDoc));

        when(documentService.splitDocuments(any())).thenReturn(List.of(processedDoc));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run increments the failed counter when an IngestionException is thrown")
    void run_WhenIngestionExceptionOccurs_ThenIncrementsFailedCounter() {
        // given
        S3Object obj = S3Object.builder().key("documents/report.pdf").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);

        // S3 client throwing arbitrary unchecked exceptions
        when(s3Client.getObject(any(GetObjectRequest.class)))
                .thenThrow(new IngestionException("IO Stream crash"));

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.failed).isEqualTo(1);
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run rolls back metadata marker on ingestion failure so subsequent runs can retry")
    void run_WhenIngestionFails_ThenRollsBackMetadataMarkerSoRetryIsPossible() {
        // given — first claim succeeds, then ingestion fails; we expect the marker to be removed
        // so a subsequent run for the same ETag is not skipped while Qdrant has no points.
        S3Object obj = S3Object.builder().key("documents/report.pdf").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);

        when(s3Client.getObject(any(GetObjectRequest.class)))
                .thenThrow(new IngestionException("simulated mid-ingestion failure"));

        // when
        manualIngestionService.run(Optional.empty(), "openai");

        // then — the metadata key that was put-if-absent gets removed so future runs retry
        verify(metadataStore).remove(argThat(s -> s != null && s.startsWith("manual-ingestion:documents/report.pdf:")));
    }

    @Test
    @DisplayName("run uses ETag value in the metadata key when the S3 object has an ETag")
    void run_WhenMarkdownObjectHasEtag_ThenUsesEtagInMetadataKey() {
        // given
        S3Object obj = S3Object.builder().key("markdown/notes.md").eTag("abc123").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(enforceMetaKey("manual-ingestion:markdown/notes.md:abc123"), anyString()))
                .thenReturn(null);

        when(s3Client.getObject(any(GetObjectRequest.class)))
                .thenReturn(org.mockito.Mockito.<ResponseInputStream<GetObjectResponse>>mock());
        when(ingestionService.processMarkdown(any(), eq("markdown/notes.md")))
                .thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run uses ETag in the metadata key for a DOCX document with a known ETag")
    void run_WhenDocxObjectHasKnownEtag_ThenUsesEtagInMetadataKey() {
        // given — a DOCX stored under documents/ with a real eTag
        S3Object obj = S3Object.builder().key("documents/contract.docx").eTag("etag-xyz").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(enforceMetaKey("manual-ingestion:documents/contract.docx:etag-xyz"), anyString()))
                .thenReturn(null);

        when(s3Client.getObject(any(GetObjectRequest.class)))
                .thenReturn(org.mockito.Mockito.<ResponseInputStream<GetObjectResponse>>mock());
        when(ingestionService.processUnstructured(any(), eq("documents/contract.docx")))
                .thenReturn(List.of(new Document("docx text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    private String enforceMetaKey(String val) {
        return argThat(s -> s.equals(val));
    }
}
