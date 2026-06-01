package com.lukk.ascend.ai.agent.service.rag;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.dto.SourceFile;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectResponse;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.net.MalformedURLException;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class S3PresignedUrlServicePresignBranchesTest {

    @Mock
    private S3Presigner presigner;

    @Mock
    private S3Client s3Client;

    @Mock
    private RagProperties ragProperties;

    private S3PresignedUrlService service;

    @BeforeEach
    void setUp() {
        RagProperties.SourceAttachments sa = new RagProperties.SourceAttachments();
        sa.setEnabled(true);
        sa.setPresignTtl(Duration.ofMinutes(15));
        sa.setMaxFileSize(org.springframework.util.unit.DataSize.ofMegabytes(10));
        when(ragProperties.getSourceAttachments()).thenReturn(sa);

        service = new S3PresignedUrlService(presigner, s3Client, ragProperties,
                Executors.newVirtualThreadPerTaskExecutor(), "http://localhost:9070");
        service.init();
    }

    @Test
    @DisplayName("presignAll returns empty list when refs is null")
    void presignAll_NullRefs_ReturnsEmpty() {
        // then
        assertThat(service.presignAll(null)).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns empty list when refs is empty")
    void presignAll_EmptyRefs_ReturnsEmpty() {
        // then
        assertThat(service.presignAll(List.of())).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns empty list when source attachments are disabled")
    void presignAll_AttachmentsDisabled_ReturnsEmpty() {
        // given
        RagProperties.SourceAttachments sa = mock(RagProperties.SourceAttachments.class);
        when(sa.isEnabled()).thenReturn(false);
        when(ragProperties.getSourceAttachments()).thenReturn(sa);

        // then
        assertThat(service.presignAll(List.of(new SourceRef("bucket", "key.pdf", "key.pdf", null)))).isEmpty();
    }

    @Test
    @DisplayName("presignAll skips a ref when HEAD object request fails")
    void presignAll_HeadObjectFails_SkipsRef() {
        // given
        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenThrow(new RuntimeException("S3 unavailable"));

        // when
        List<SourceFile> results = service.presignAll(List.of(new SourceRef("bucket", "key.pdf", "key.pdf", null)));

        // then
        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("presignAll skips a ref when file size exceeds max file size")
    void presignAll_FileSizeExceedsMax_SkipsRef() {
        // given
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(
                HeadObjectResponse.builder().contentLength(100L * 1024 * 1024).contentType("application/pdf").build());

        // when
        List<SourceFile> results = service.presignAll(List.of(new SourceRef("bucket", "big.pdf", "big.pdf", null)));

        // then
        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns presigned URL when HEAD succeeds and size is within limit")
    void presignAll_ValidRef_ReturnsSigned() throws MalformedURLException {
        // given
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(
                HeadObjectResponse.builder().contentLength(1024L).contentType("application/pdf").build());
        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(URI.create("https://example.com/key.pdf?sig=abc").toURL());
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        // when
        List<SourceFile> results = service.presignAll(List.of(new SourceRef("bucket", "key.pdf", "key.pdf", null)));

        // then
        assertThat(results).hasSize(1);
        assertThat(results.getFirst().downloadUrl()).contains("key.pdf");
    }

    @Test
    @DisplayName("presignAll includes source when contentLength is null (size check skipped)")
    void presignAll_NullContentLength_SizeCheckSkipped() throws MalformedURLException {
        // given — contentLength() returns null -> sizeBytes != null && sizeBytes > max is false -> no skip
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(
                HeadObjectResponse.builder().contentLength(null).contentType("application/pdf").build());
        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(URI.create("https://example.com/key.pdf?sig=abc").toURL());
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        // when
        List<SourceFile> results = service.presignAll(List.of(new SourceRef("bucket", "key.pdf", "key.pdf", null)));

        // then
        assertThat(results).hasSize(1);
    }

    @Test
    @DisplayName("presignAll uses SourceRef mimeType when it is present instead of HEAD response contentType")
    void presignAll_RefHasMimeType_UsesRefMimeType() throws MalformedURLException {
        // given
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(
                HeadObjectResponse.builder().contentLength(512L).contentType("application/octet-stream").build());
        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(URI.create("https://example.com/img.png?sig=abc").toURL());
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        // when
        List<SourceFile> results = service.presignAll(List.of(new SourceRef("bucket", "img.png", "img.png", "image/png")));

        // then
        assertThat(results).hasSize(1);
        assertThat(results.getFirst().mimeType()).isEqualTo("image/png");
    }
}
