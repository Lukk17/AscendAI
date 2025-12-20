package com.lukk.ascend.ai.orchestrator.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class StorageServiceTest {

    @Mock
    private S3Client s3Client;

    @InjectMocks
    private StorageService storageService;

    @BeforeEach
    void setUp() {
        ReflectionTestUtils.setField(storageService, "s3Bucket", "test-bucket");
    }

    @Test
    void uploadFile_ShouldCallS3PutObject() throws IOException {
        // given
        String key = "test/file.txt";
        byte[] content = "hello".getBytes();
        InputStream inputStream = new ByteArrayInputStream(content);
        long size = content.length;

        // when
        storageService.uploadFile(key, inputStream, size);

        // then
        verify(s3Client, times(1)).putObject(any(PutObjectRequest.class), any(RequestBody.class));
    }

    @Test
    void uploadFile_ShouldThrowIOException_WhenS3ClientThrows() {
        // given
        String key = "test/file.txt";
        byte[] content = "hello".getBytes();
        InputStream inputStream = new ByteArrayInputStream(content);
        long size = content.length;

        when(s3Client.putObject(any(PutObjectRequest.class), any(RequestBody.class)))
                .thenThrow(new RuntimeException("S3 Error"));

        // when & then
        assertThrows(IOException.class, () -> storageService.uploadFile(key, inputStream, size));
    }
}
