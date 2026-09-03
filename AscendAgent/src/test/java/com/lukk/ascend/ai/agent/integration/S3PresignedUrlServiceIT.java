package com.lukk.ascend.ai.agent.integration;

import com.lukk.ascend.ai.agent.dto.SourceFile;
import com.lukk.ascend.ai.agent.service.rag.S3PresignedUrlService;
import com.lukk.ascend.ai.agent.service.rag.SourceRef;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import software.amazon.awssdk.core.sync.RequestBody;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.PutObjectRequest;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Proves the {@code rag-source-attachments} scenario "URL resolves against an endpoint that
 * does not validate credentials" against the real Floci container, not a mock. A presigned URL
 * signed with the agent's configured (unauthenticated-on-Floci) credentials must still resolve
 * to the exact object bytes, byte-identical to a direct unauthenticated GET of the same key.
 */
class S3PresignedUrlServiceIT extends TestcontainersBase {

    private static final String BUCKET = "knowledge-base";
    private static final String KEY = "documents/presign-it.txt";
    private static final byte[] CONTENT = "presigned-url-it-fixture".getBytes(StandardCharsets.UTF_8);

    @Autowired
    S3Client s3Client;

    @Autowired
    S3PresignedUrlService presignedUrlService;

    @Test
    void presignedUrl_resolvesAgainstFlociWithoutCredentialValidation() throws Exception {
        s3Client.putObject(
                PutObjectRequest.builder().bucket(BUCKET).key(KEY).build(),
                RequestBody.fromBytes(CONTENT));

        SourceRef ref = new SourceRef(BUCKET, KEY, "presign-it.txt", "text/plain");
        List<SourceFile> sources = presignedUrlService.presignAll(List.of(ref));

        assertThat(sources).hasSize(1);
        String downloadUrl = sources.getFirst().downloadUrl();
        assertThat(downloadUrl).contains("X-Amz-Signature");

        HttpClient http = HttpClient.newHttpClient();

        HttpResponse<byte[]> presignedResponse = http.send(
                HttpRequest.newBuilder(URI.create(downloadUrl)).GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(presignedResponse.statusCode()).isEqualTo(200);
        assertThat(presignedResponse.body()).isEqualTo(CONTENT);

        String directUrl = "http://" + FLOCI.getHost() + ":" + FLOCI.getMappedPort(FLOCI_EDGE_PORT)
                + "/" + BUCKET + "/" + KEY;
        HttpResponse<byte[]> directResponse = http.send(
                HttpRequest.newBuilder(URI.create(directUrl)).GET().build(),
                HttpResponse.BodyHandlers.ofByteArray());
        assertThat(directResponse.statusCode()).isEqualTo(200);
        assertThat(presignedResponse.body()).isEqualTo(directResponse.body());
    }
}
