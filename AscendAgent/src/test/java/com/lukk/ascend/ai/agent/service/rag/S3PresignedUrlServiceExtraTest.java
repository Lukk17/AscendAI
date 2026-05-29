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
import java.net.URL;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Extra branch coverage for S3PresignedUrlService:
 *  - presignAll when refs are null
 *  - presignAll when source attachments are disabled
 *  - presignAll when HEAD object fails (returns Optional.empty)
 *  - presignAll when object size exceeds maxFileSize
 *  - presignAll when source has a non-null mimeType in SourceRef (uses it instead of HEAD)
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class S3PresignedUrlServiceExtraTest {

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
        assertThat(service.presignAll(null)).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns empty list when refs is empty")
    void presignAll_EmptyRefs_ReturnsEmpty() {
        assertThat(service.presignAll(List.of())).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns empty list when source attachments are disabled")
    void presignAll_AttachmentsDisabled_ReturnsEmpty() {
        RagProperties.SourceAttachments sa = mock(RagProperties.SourceAttachments.class);
        when(sa.isEnabled()).thenReturn(false);
        when(ragProperties.getSourceAttachments()).thenReturn(sa);

        SourceRef ref = new SourceRef("bucket", "key.pdf", "key.pdf", null);
        assertThat(service.presignAll(List.of(ref))).isEmpty();
    }

    @Test
    @DisplayName("presignAll skips a ref when HEAD object request fails")
    void presignAll_HeadObjectFails_SkipsRef() {
        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenThrow(new RuntimeException("S3 unavailable"));

        SourceRef ref = new SourceRef("bucket", "key.pdf", "key.pdf", null);
        List<SourceFile> results = service.presignAll(List.of(ref));

        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("presignAll skips a ref when file size exceeds max file size")
    void presignAll_FileSizeExceedsMax_SkipsRef() {
        HeadObjectResponse head = HeadObjectResponse.builder()
                .contentLength(100L * 1024 * 1024) // 100MB > 10MB limit
                .contentType("application/pdf")
                .build();
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(head);

        SourceRef ref = new SourceRef("bucket", "big.pdf", "big.pdf", null);
        List<SourceFile> results = service.presignAll(List.of(ref));

        assertThat(results).isEmpty();
    }

    @Test
    @DisplayName("presignAll returns presigned URL when HEAD succeeds and size is within limit")
    void presignAll_ValidRef_ReturnsSigned() throws MalformedURLException {
        HeadObjectResponse head = HeadObjectResponse.builder()
                .contentLength(1024L)
                .contentType("application/pdf")
                .build();
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(head);

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://example.com/key.pdf?sig=abc"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        SourceRef ref = new SourceRef("bucket", "key.pdf", "key.pdf", null);
        List<SourceFile> results = service.presignAll(List.of(ref));

        assertThat(results).hasSize(1);
        assertThat(results.getFirst().downloadUrl()).contains("key.pdf");
    }

    @Test
    @DisplayName("presignAll includes source when contentLength is null (size check skipped)")
    void presignAll_NullContentLength_SizeCheckSkipped() throws MalformedURLException {
        // contentLength() returns null -> sizeBytes != null && sizeBytes > max is false -> no skip
        HeadObjectResponse head = HeadObjectResponse.builder()
                .contentLength(null)
                .contentType("application/pdf")
                .build();
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(head);

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://example.com/key.pdf?sig=abc"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        SourceRef ref = new SourceRef("bucket", "key.pdf", "key.pdf", null);
        List<SourceFile> results = service.presignAll(List.of(ref));

        assertThat(results).hasSize(1);
    }

    @Test
    @DisplayName("presignAll uses SourceRef mimeType when it is present instead of HEAD response contentType")
    void presignAll_RefHasMimeType_UsesRefMimeType() throws MalformedURLException {
        HeadObjectResponse head = HeadObjectResponse.builder()
                .contentLength(512L)
                .contentType("application/octet-stream") // would be overridden
                .build();
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(head);

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://example.com/img.png?sig=abc"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        SourceRef ref = new SourceRef("bucket", "img.png", "img.png", "image/png");
        List<SourceFile> results = service.presignAll(List.of(ref));

        assertThat(results).hasSize(1);
        assertThat(results.getFirst().mimeType()).isEqualTo("image/png");
    }
}
