package com.lukk.ascend.ai.agent.service.ingestion;
import com.lukk.ascend.ai.agent.service.provider.VectorStoreResolver;

import com.lukk.ascend.ai.agent.service.ingestion.IngestionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.test.util.ReflectionTestUtils;
import software.amazon.awssdk.core.ResponseInputStream;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Request;
import software.amazon.awssdk.services.s3.model.ListObjectsV2Response;
import software.amazon.awssdk.services.s3.model.S3Object;

import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Covers the IOException path in ManualIngestionService.ingestObject.
 * Requires a stream that throws IOException when the try-with-resources closes it.
 */
@ExtendWith(MockitoExtension.class)
class ManualIngestionServiceIOExceptionTest {

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

    @InjectMocks
    private ManualIngestionService service;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(service, "bucket", "test-bucket");
        ReflectionTestUtils.setField(service, "markdownFolder", "markdown/");
        ReflectionTestUtils.setField(service, "documentsFolder", "documents/");
    }

    @Test
    @DisplayName("ingestObject catches IngestionException from stream and increments failed counter")
    void ingestObject_IngestionExceptionFromProcessMarkdown_IncrementsFailedCounter() throws Exception {
        // given
        S3Object obj = S3Object.builder().key("markdown/broken.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);

        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);

        // Make processMarkdown throw IngestionException -> caught by IngestionException block
        when(ingestionService.processMarkdown(any(), anyString()))
                .thenThrow(new com.lukk.ascend.ai.agent.exception.IngestionException("parse failed"));

        // when
        ManualIngestionService.ManualIngestionResult result = service.run(Optional.empty(), "openai");

        // then
        assertThat(result.failed).isEqualTo(1);
        verify(metadataStore).remove(anyString());
    }

    @Test
    @DisplayName("ingestObject rethrows as IngestionException when ResponseInputStream close throws IOException")
    void ingestObject_IOExceptionOnStreamClose_WrapsAndRethrows() throws Exception {
        // given — a ResponseInputStream whose close() throws IOException, triggering the IOException catch
        S3Object obj = S3Object.builder().key("markdown/broken.md").lastModified(Instant.now()).build();
        ListObjectsV2Response response = ListObjectsV2Response.builder().contents(List.of(obj)).build();
        when(s3Client.listObjectsV2(any(ListObjectsV2Request.class))).thenReturn(response);
        when(metadataStore.putIfAbsent(anyString(), anyString())).thenReturn(null);

        ResponseInputStream<GetObjectResponse> mockStream = mock();
        when(s3Client.getObject(any(GetObjectRequest.class))).thenReturn(mockStream);

        // processMarkdown succeeds (returns docs), but then close() throws IOException
        List<org.springframework.ai.document.Document> docs = List.of(new org.springframework.ai.document.Document("text"));
        when(ingestionService.processMarkdown(any(), anyString())).thenReturn(docs);
        when(documentService.splitDocuments(any())).thenReturn(docs);
        when(vectorStoreResolver.resolve(anyString())).thenReturn(mock(org.springframework.ai.vectorstore.VectorStore.class));
        org.mockito.Mockito.doThrow(new IOException("close failed")).when(mockStream).close();

        // when — IOException from stream.close() -> caught by IOException block -> rethrown as IngestionException
        assertThatThrownBy(() -> service.run(Optional.empty(), "openai"))
                .isInstanceOf(com.lukk.ascend.ai.agent.exception.IngestionException.class)
                .hasMessageContaining("Failed to read S3 object");

        // And the metadata marker should be removed
        verify(metadataStore).remove(anyString());
    }
}
