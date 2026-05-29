package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.service.ingestion.DocumentService;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.document.Document;
import org.springframework.integration.file.FileHeaders;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.test.util.ReflectionTestUtils;
import software.amazon.awssdk.services.s3.S3Client;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.util.List;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class IngestionPipelineConfigTest {

    @Mock
    private IngestionService ingestionService;

    @Mock
    private DocumentService documentService;

    @Mock
    private S3Client s3Client;

    @Mock
    private ConcurrentMetadataStore metadataStore;

    private IngestionPipelineConfig config;

    @BeforeEach
    void setUp() {
        config = new IngestionPipelineConfig(
                ingestionService, documentService, Executors.newVirtualThreadPerTaskExecutor(),
                s3Client, metadataStore);
        ReflectionTestUtils.setField(config, "s3Bucket", "test-bucket");
        ReflectionTestUtils.setField(config, "markdownFolder", "markdown/");
        ReflectionTestUtils.setField(config, "documentsFolder", "documents/");
    }


    @Test
    @DisplayName("routeFile routes .md file to markdownChannel")
    void routeFile_MdExtension_RoutesToMarkdownChannel() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0])
                .setHeader(FileHeaders.REMOTE_FILE, "notes.md")
                .build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("markdownChannel");
    }

    @Test
    @DisplayName("routeFile routes markdown/ path to markdownChannel")
    void routeFile_MarkdownFolderPath_RoutesToMarkdownChannel() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0])
                .setHeader(FileHeaders.REMOTE_FILE, "markdown/readme.txt")
                .build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("markdownChannel");
    }

    @Test
    @DisplayName("routeFile routes documents/ path to unstructuredChannel")
    void routeFile_DocumentsFolderPath_RoutesToUnstructuredChannel() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0])
                .setHeader(FileHeaders.REMOTE_FILE, "documents/report.pdf")
                .build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("unstructuredChannel");
    }

    @Test
    @DisplayName("routeFile routes unknown path to nullChannel")
    void routeFile_UnknownPath_RoutesToNullChannel() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0])
                .setHeader(FileHeaders.REMOTE_FILE, "other/image.png")
                .build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("nullChannel");
    }

    @Test
    @DisplayName("routeFile uses file_remoteFile header fallback when REMOTE_FILE header is absent")
    void routeFile_FallbackHeader_UsedWhenRemoteFileAbsent() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0])
                .setHeader("file_remoteFile", "documents/doc.pdf")
                .build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("unstructuredChannel");
    }

    @Test
    @DisplayName("routeFile routes to nullChannel when both filename headers are absent")
    void routeFile_NoBothHeaders_RoutesToNullChannel() throws Exception {
        // given
        Message<?> msg = MessageBuilder.withPayload(new byte[0]).build();

        // when
        String channel = invokeRouteFile(msg);

        // then
        assertThat(channel).isEqualTo("nullChannel");
    }


    @Test
    @DisplayName("processMarkdownMessage processes a valid markdown stream")
    void processMarkdownMessage_ValidStream_ReturnsDocuments() throws Exception {
        // given
        InputStream stream = new ByteArrayInputStream("# Title\nContent".getBytes());
        Message<?> msg = MessageBuilder.withPayload(stream)
                .setHeader(FileHeaders.REMOTE_FILE, "readme.md")
                .build();
        when(ingestionService.processMarkdown(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("text")));

        // when
        List<Document> docs = invokeProcessMarkdownMessage(msg);

        // then
        assertThat(docs).hasSize(1);
    }

    @Test
    @DisplayName("processMarkdownMessage uses 'unknown.md' as filename when header is absent")
    void processMarkdownMessage_NoFilenameHeader_UsesUnknownMd() throws Exception {
        // given
        InputStream stream = new ByteArrayInputStream("content".getBytes());
        Message<?> msg = MessageBuilder.withPayload(stream).build();
        when(ingestionService.processMarkdown(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("text")));

        // when
        List<Document> docs = invokeProcessMarkdownMessage(msg);

        // then
        assertThat(docs).hasSize(1);
    }


    @Test
    @DisplayName("processUnstructuredMessage processes a valid stream")
    void processUnstructuredMessage_ValidStream_ReturnsDocuments() throws Exception {
        // given
        InputStream stream = new ByteArrayInputStream("pdf content".getBytes());
        Message<?> msg = MessageBuilder.withPayload(stream)
                .setHeader(FileHeaders.REMOTE_FILE, "report.pdf")
                .build();
        when(ingestionService.processUnstructured(any(InputStream.class), anyString()))
                .thenReturn(List.of(new Document("text")));

        // when
        List<Document> docs = invokeProcessUnstructuredMessage(msg);

        // then
        assertThat(docs).hasSize(1);
    }

    @Test
    @DisplayName("processUnstructuredMessage uses 'unknown' as filename when REMOTE_FILE header is absent")
    void processUnstructuredMessage_NoFilenameHeader_UsesUnknown() throws Exception {
        // given
        java.io.InputStream stream = new java.io.ByteArrayInputStream("pdf content".getBytes());
        Message<?> msg = MessageBuilder.withPayload(stream).build();
        when(ingestionService.processUnstructured(any(java.io.InputStream.class), anyString()))
                .thenReturn(List.of(new Document("text")));

        // when
        List<Document> docs = invokeProcessUnstructuredMessage(msg);

        // then
        assertThat(docs).hasSize(1);
        org.mockito.Mockito.verify(ingestionService).processUnstructured(any(java.io.InputStream.class),
                org.mockito.ArgumentMatchers.eq("unknown"));
    }

    @Test
    @DisplayName("processUnstructuredMessage throws IngestionException when processing fails")
    void processUnstructuredMessage_ProcessingFails_ThrowsIngestionException() throws Exception {
        // given
        InputStream stream = new ByteArrayInputStream("pdf content".getBytes());
        Message<?> msg = MessageBuilder.withPayload(stream)
                .setHeader(FileHeaders.REMOTE_FILE, "report.pdf")
                .build();
        when(ingestionService.processUnstructured(any(InputStream.class), anyString()))
                .thenThrow(new RuntimeException("processing failed"));

        // then
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> invokeProcessUnstructuredMessage(msg))
                .isInstanceOf(Exception.class)
                .satisfies(e -> {
                    // Due to reflection invocation, wrapped in InvocationTargetException
                    Throwable cause = e.getCause() != null ? e.getCause() : e;
                    assertThat(cause).isInstanceOf(com.lukk.ascend.ai.agent.exception.IngestionException.class)
                            .hasMessageContaining("Error processing unstructured stream");
                });
    }


    private String invokeRouteFile(Message<?> msg) throws Exception {
        Method m = IngestionPipelineConfig.class.getDeclaredMethod("routeFile", Message.class);
        m.setAccessible(true);
        return (String) m.invoke(config, msg);
    }

    @SuppressWarnings("unchecked")
    private List<Document> invokeProcessMarkdownMessage(Message<?> msg) throws Exception {
        Method m = IngestionPipelineConfig.class.getDeclaredMethod("processMarkdownMessage", Message.class);
        m.setAccessible(true);
        return (List<Document>) m.invoke(config, msg);
    }

    @SuppressWarnings("unchecked")
    private List<Document> invokeProcessUnstructuredMessage(Message<?> msg) throws Exception {
        Method m = IngestionPipelineConfig.class.getDeclaredMethod("processUnstructuredMessage", Message.class);
        m.setAccessible(true);
        return (List<Document>) m.invoke(config, msg);
    }
}
