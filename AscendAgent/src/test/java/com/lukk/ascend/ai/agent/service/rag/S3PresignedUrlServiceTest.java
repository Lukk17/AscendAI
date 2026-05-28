package com.lukk.ascend.ai.agent.service.rag;

import com.lukk.ascend.ai.agent.config.properties.RagProperties;
import com.lukk.ascend.ai.agent.dto.SourceFile;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.util.unit.DataSize;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.HeadObjectRequest;
import software.amazon.awssdk.services.s3.model.HeadObjectResponse;
import software.amazon.awssdk.services.s3.model.S3Exception;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.GetObjectPresignRequest;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.net.URL;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.Executor;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class S3PresignedUrlServiceTest {

    @Mock
    private S3Presigner presigner;

    @Mock
    private S3Client s3Client;

    private RagProperties ragProperties;
    private S3PresignedUrlService service;
    private final Executor sameThreadExecutor = Runnable::run;

    @BeforeEach
    void setUp() {
        ragProperties = new RagProperties();
        ragProperties.getSourceAttachments().setMaxFileSize(DataSize.ofMegabytes(25));
        ragProperties.getSourceAttachments().setPresignTtl(Duration.ofMinutes(15));
        service = new S3PresignedUrlService(presigner, s3Client, ragProperties, sameThreadExecutor,
                "http://localhost:9070");
        service.init();
    }

    @Test
    void presignAll_HappyPath_ReturnsUrlAndSize() throws Exception {
        SourceRef ref = new SourceRef("bucket", "manual.pdf", "manual.pdf", null);

        HeadObjectResponse head = HeadObjectResponse.builder()
                .contentLength(2048L)
                .contentType("application/pdf")
                .build();
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(head);

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://minio.example/bucket/manual.pdf?X-Amz-Signature=abc"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        List<SourceFile> result = service.presignAll(List.of(ref));

        assertThat(result).hasSize(1);
        SourceFile f = result.getFirst();
        assertThat(f.name()).isEqualTo("manual.pdf");
        assertThat(f.mimeType()).isEqualTo("application/pdf");
        assertThat(f.downloadUrl()).contains("X-Amz-Signature");
        assertThat(f.sizeBytes()).isEqualTo(2048L);
        assertThat(f.expiresAt()).isNotNull();
    }

    @Test
    void presignAll_OversizeObject_IsSkippedAndLogsWarn() {
        SourceRef ref = new SourceRef("bucket", "huge.pdf", "huge.pdf", null);
        when(s3Client.headObject(any(HeadObjectRequest.class))).thenReturn(
                HeadObjectResponse.builder().contentLength(50L * 1024 * 1024).contentType("application/pdf").build());

        List<SourceFile> result = service.presignAll(List.of(ref));

        assertThat(result).isEmpty();
        verify(presigner, never()).presignGetObject(any(GetObjectPresignRequest.class));
    }

    @Test
    void presignAll_HeadFails_OmitsSourceButContinues() throws Exception {
        SourceRef good = new SourceRef("bucket", "good.pdf", "good.pdf", "application/pdf");
        SourceRef bad = new SourceRef("bucket", "bad.pdf", "bad.pdf", "application/pdf");

        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenAnswer(inv -> {
                    HeadObjectRequest req = inv.getArgument(0);
                    if (req.key().equals("bad.pdf")) {
                        throw S3Exception.builder().message("503").build();
                    }
                    return HeadObjectResponse.builder().contentLength(100L).contentType("application/pdf").build();
                });

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://minio.example/bucket/good.pdf?sig=abc"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        List<SourceFile> result = service.presignAll(List.of(good, bad));

        assertThat(result).hasSize(1);
        assertThat(result.getFirst().name()).isEqualTo("good.pdf");
    }

    @Test
    void presignAll_PresignerThrows_OmitsSource() {
        SourceRef ref = new SourceRef("bucket", "x.pdf", "x.pdf", "application/pdf");
        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenReturn(HeadObjectResponse.builder().contentLength(100L).contentType("application/pdf").build());
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class)))
                .thenThrow(S3Exception.builder().message("signing failed").build());

        List<SourceFile> result = service.presignAll(List.of(ref));

        assertThat(result).isEmpty();
    }

    @Test
    void presignAll_ParallelPresignsThree() throws Exception {
        SourceRef a = new SourceRef("b", "a.pdf", "a.pdf", "application/pdf");
        SourceRef b = new SourceRef("b", "b.pdf", "b.pdf", "application/pdf");
        SourceRef c = new SourceRef("b", "c.pdf", "c.pdf", "application/pdf");

        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenReturn(HeadObjectResponse.builder().contentLength(10L).contentType("application/pdf").build());

        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        when(presigned.url()).thenReturn(new URL("https://minio.example/b/x?sig=1"));
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        List<SourceFile> result = service.presignAll(List.of(a, b, c));

        assertThat(result).hasSize(3);
        verify(presigner, times(3)).presignGetObject(any(GetObjectPresignRequest.class));
    }

    @Test
    void presignAll_DisabledKillSwitch_ReturnsEmpty() {
        ragProperties.getSourceAttachments().setEnabled(false);
        SourceRef ref = new SourceRef("b", "a.pdf", "a.pdf", null);

        List<SourceFile> result = service.presignAll(List.of(ref));

        assertThat(result).isEmpty();
        verify(s3Client, never()).headObject(any(HeadObjectRequest.class));
    }

    @Test
    void presignAll_EmptyInput_ReturnsEmpty() {
        assertThat(service.presignAll(List.of())).isEmpty();
        assertThat(service.presignAll(null)).isEmpty();
    }

    @Test
    void init_ClampsTtlAboveMax() {
        ragProperties.getSourceAttachments().setPresignTtl(Duration.ofHours(2));
        S3PresignedUrlService clamped = new S3PresignedUrlService(presigner, s3Client, ragProperties,
                sameThreadExecutor, "http://localhost:9070");
        clamped.init();

        SourceRef ref = new SourceRef("b", "a.pdf", "a.pdf", "application/pdf");
        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenReturn(HeadObjectResponse.builder().contentLength(10L).contentType("application/pdf").build());
        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        try {
            when(presigned.url()).thenReturn(new URL("https://minio.example/b/a?sig=1"));
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        List<SourceFile> result = clamped.presignAll(List.of(ref));

        assertThat(result).hasSize(1);
        // expiresAt should be approximately 1 hour out, not 2
        long secondsToExpiry = java.time.Duration.between(java.time.Instant.now(), result.getFirst().expiresAt()).getSeconds();
        assertThat(secondsToExpiry).isBetween(3500L, 3700L);
    }

    @Test
    void init_ClampsTtlBelowMin() {
        ragProperties.getSourceAttachments().setPresignTtl(Duration.ofSeconds(10));
        S3PresignedUrlService clamped = new S3PresignedUrlService(presigner, s3Client, ragProperties,
                sameThreadExecutor, "http://localhost:9070");
        clamped.init();

        SourceRef ref = new SourceRef("b", "a.pdf", "a.pdf", "application/pdf");
        when(s3Client.headObject(any(HeadObjectRequest.class)))
                .thenReturn(HeadObjectResponse.builder().contentLength(10L).contentType("application/pdf").build());
        PresignedGetObjectRequest presigned = mock(PresignedGetObjectRequest.class);
        try {
            when(presigned.url()).thenReturn(new URL("https://minio.example/b/a?sig=1"));
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
        when(presigner.presignGetObject(any(GetObjectPresignRequest.class))).thenReturn(presigned);

        List<SourceFile> result = clamped.presignAll(List.of(ref));

        assertThat(result).hasSize(1);
        // clamped to 1 minute = 60s (not 10s)
        long secondsToExpiry = java.time.Duration.between(java.time.Instant.now(), result.getFirst().expiresAt()).getSeconds();
        assertThat(secondsToExpiry).isBetween(50L, 70L);
    }
}
