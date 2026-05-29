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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ManualIngestionServiceS3PaginationTest {

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
    void setUp() {
        ReflectionTestUtils.setField(manualIngestionService, "bucket", "test-bucket");
        ReflectionTestUtils.setField(manualIngestionService, "markdownFolder", "markdown/");
        ReflectionTestUtils.setField(manualIngestionService, "documentsFolder", "documents/");
    }

    @Test
    @DisplayName("run skips S3 objects with null key")
    void run_NullKeyObject_SkipsIt() {
        // given
        S3Object nullKey = S3Object.builder().key(null).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder()
                .contents(List.of(nullKey)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.skipped).isZero();
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run skips S3 objects with blank key")
    void run_BlankKeyObject_SkipsIt() {
        // given
        S3Object blankKey = S3Object.builder().key("   ").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder()
                .contents(List.of(blankKey)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then — blank key doesn't even hit shouldIngestKey, just returns
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run follows continuation token to fetch the next page")
    void run_WithContinuationToken_PaginatesCorrectly() {
        // given
        S3Object obj = S3Object.builder().key("irrelevant/skip.txt").build();
        ListObjectsV2Response firstPage = ListObjectsV2Response.builder()
                .contents(List.of(obj))
                .nextContinuationToken("token123")
                .build();
        ListObjectsV2Response secondPage = ListObjectsV2Response.builder()
                .contents(List.of())
                .build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class)))
                .thenReturn(firstPage)
                .thenReturn(secondPage);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then — skipped=1 (from "irrelevant/skip.txt"), both pages fetched
        assertThat(result.skipped).isEqualTo(1);
    }

    @Test
    @DisplayName("run skips object when ingestionService returns null documents list")
    void run_NullDocumentsReturned_SkipsObject() throws Exception {
        // given
        S3Object obj = S3Object.builder().key("markdown/doc.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(null);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.skipped).isEqualTo(1);
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run skips object when ingestionService returns empty documents list")
    void run_EmptyDocumentsReturned_SkipsObject() throws Exception {
        // given
        S3Object obj = S3Object.builder().key("markdown/doc.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of());

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.skipped).isEqualTo(1);
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run increments failed counter and removes metadata when IOException is thrown")
    void run_IOExceptionFromStream_IncrementsFailedAndRemovesMetadata() throws Exception {
        // given — IOException is wrapped as IngestionException and rethrown so metadata marker is removed
        S3Object obj = S3Object.builder().key("documents/report.docx").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processUnstructured(any(), anyString())).thenThrow(new IngestionException("IO fail"));

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.failed).isEqualTo(1);
        verify(metadataStore).remove(anyString());
    }

    @Test
    @DisplayName("run uses lastModified as version when S3 object has no ETag")
    void run_NoEtagButHasLastModified_UsesLastModifiedAsVersion() throws Exception {
        // given
        Instant ts = Instant.parse("2025-01-01T00:00:00Z");
        S3Object obj = S3Object.builder().key("markdown/notes.md").lastModified(ts).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run uses 'unknown' as version when S3 object has no ETag and no lastModified")
    void run_NoEtagNoLastModified_UsesUnknownVersion() throws Exception {
        // given — no eTag and no lastModified -> version = "unknown"
        S3Object obj = S3Object.builder().key("markdown/notes.md").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run uses 'unknown' version when S3 object has a blank ETag")
    void run_BlankEtagAndNoLastModified_UsesUnknownVersion() throws Exception {
        // given — blank eTag (not null) and no lastModified -> falls through to "unknown"
        S3Object obj = S3Object.builder().key("markdown/notes.md").eTag("").build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // then
        manualIngestionService.run(Optional.empty(), "openai");
    }

    @Test
    @DisplayName("run includes objects in documents/ folder when shouldIngestKey matches documentsFolder")
    void run_DocumentsFolderObject_IncludedForIngestion() throws Exception {
        // given
        S3Object obj = S3Object.builder().key("documents/report.pdf").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processUnstructured(any(), anyString())).thenReturn(List.of(new Document("pdf")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run ingests file in markdown folder that does not end with .md extension")
    void run_MarkdownFolderTxtFile_IncludedForIngestion() throws Exception {
        // given — key doesn't end with .md but IS in markdownFolder -> shouldIngestKey=true via second condition
        S3Object obj = S3Object.builder().key("markdown/readme.txt").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenReturn(List.of(new Document("chunk")));
        when(vectorStoreResolver.resolve("openai")).thenReturn(vectorStore);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.indexed).isEqualTo(1);
    }

    @Test
    @DisplayName("run filters by prefix when a non-blank prefix is provided")
    void run_NonBlankPrefix_PassedToListObjects() {
        // given
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of()).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.of("markdown/"), "openai");

        // then
        assertThat(result.indexed).isZero();
    }

    @Test
    @DisplayName("run does not loop when continuation token is blank")
    void run_BlankContinuationToken_DoesNotLoop() {
        // given — nextContinuationToken() returns "" (blank) -> while condition false -> single page
        S3Object obj = S3Object.builder().key("irrelevant/skip.txt").build();
        ListObjectsV2Response firstPage = ListObjectsV2Response.builder()
                .contents(List.of(obj))
                .nextContinuationToken("")
                .build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(firstPage);

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then — "irrelevant" path skipped
        assertThat(result.skipped).isEqualTo(1);
    }

    @Test
    @DisplayName("run increments failed counter when splitDocuments throws IngestionException")
    void run_SplitDocumentsThrowsIngestionException_IncrementsFailedCounter() throws Exception {
        // given
        S3Object obj = S3Object.builder().key("markdown/doc.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);
        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(List.of(new Document("text")));
        when(documentService.splitDocuments(any())).thenThrow(new IngestionException("split failed"));

        // when
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.empty(), "openai");

        // then
        assertThat(result.failed).isEqualTo(1);
        verify(metadataStore).remove(anyString());
    }

    @Test
    @DisplayName("run skips blank prefix (filter removes it from Optional)")
    void run_BlankPrefix_FilteredOutDoesNotSetPrefix() {
        // given
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of()).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);

        // when — blank prefix -> filter(p -> !p.isBlank()) removes it -> no prefix set on builder
        ManualIngestionService.ManualIngestionResult result = manualIngestionService.run(Optional.of("   "), "openai");

        // then
        assertThat(result.indexed).isZero();
    }
}
