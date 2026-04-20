package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.exception.IngestionException;
import com.lukk.ascend.ai.agent.service.DocumentService;
import com.lukk.ascend.ai.agent.service.ingestion.IngestionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.integration.annotation.InboundChannelAdapter;
import org.springframework.integration.annotation.Poller;
import org.springframework.integration.aws.inbound.S3StreamingMessageSource;
import org.springframework.integration.aws.support.S3RemoteFileTemplate;
import org.springframework.integration.aws.support.S3SessionFactory;
import org.springframework.integration.aws.support.filters.S3PersistentAcceptOnceFileListFilter;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.channel.ExecutorChannel;
import org.springframework.integration.core.GenericHandler;
import org.springframework.integration.core.MessageSource;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.file.FileHeaders;
import org.springframework.integration.file.filters.CompositeFileListFilter;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.S3Object;

import java.io.InputStream;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.Executor;

@Configuration
@RequiredArgsConstructor
@Slf4j
@ConditionalOnProperty(prefix = "app.ingestion.auto", name = "enabled", havingValue = "true")
public class IngestionPipelineConfig {

    private final IngestionService ingestionService;
    private final DocumentService documentService;
    private final Executor taskExecutor;
    private final S3Client s3Client;
    private final ConcurrentMetadataStore metadataStore;

    @Value("${app.s3.bucket}")
    private String s3Bucket;

    @Value("${app.ingestion.folders.obsidian:obsidian/}")
    private String obsidianFolder;

    @Value("${app.ingestion.folders.documents:documents/}")
    private String documentsFolder;

    /**
     * Configures the S3 Message Source for streaming files.
     * <p>
     * Instead of downloading files to local disk, this source provides an
     * InputStream
     * to the file content on S3. It uses a persistent filter to prevent
     * re-ingestion.
     * </p>
     *
     * @return The configured MessageSource.
     */
    @Bean
    @InboundChannelAdapter(value = "s3Channel", poller = @Poller(fixedDelay = "${app.ingestion.poller.fixed-delay-millis:1000}", maxMessagesPerPoll = "${app.ingestion.poller.max-messages-per-poll:20}", errorChannel = "errorChannel"))
    public MessageSource<InputStream> s3MessageSource() {
        S3SessionFactory s3SessionFactory = new S3SessionFactory(s3Client);
        S3StreamingMessageSource messageSource = new S3StreamingMessageSource(
                new S3RemoteFileTemplate(s3SessionFactory),
                Comparator.comparing(S3Object::lastModified));

        messageSource.setRemoteDirectory(s3Bucket);
        messageSource.setFilter(createPersistentS3Filter(metadataStore));

        return messageSource;
    }

    private CompositeFileListFilter<S3Object> createPersistentS3Filter(ConcurrentMetadataStore metadataStore) {
        CompositeFileListFilter<S3Object> filter = new CompositeFileListFilter<>();
        filter.addFilter(new S3PersistentAcceptOnceFileListFilter(
                metadataStore, "s3-streaming-metadata"));
        return filter;
    }

    @Bean
    public MessageChannel s3Channel() {
        return new ExecutorChannel(taskExecutor);
    }

    @Bean
    public MessageChannel markdownChannel() {
        return new DirectChannel();
    }

    @Bean
    public MessageChannel unstructuredChannel() {
        return new DirectChannel();
    }

    @Bean
    public MessageChannel errorChannel() {
        DirectChannel channel = new DirectChannel();
        channel.subscribe(message -> log.error("Error in ingestion pipeline: {}", message.getPayload()));
        return channel;
    }

    @Bean
    public IntegrationFlow ingestionFlow() {
        return IntegrationFlow.from(s3Channel())
                .route(Message.class, this::routeFile)
                .get();
    }

    private String routeFile(Message<?> message) {
        String filename = (String) message.getHeaders().get(FileHeaders.REMOTE_FILE);
        if (filename == null) {
            filename = (String) message.getHeaders().get("file_remoteFile");
        }

        if (filename == null) {
            log.warn("Could not determine filename from headers. Headers: {}", message.getHeaders());
            return "nullChannel";
        }

        String path = filename.toLowerCase();
        log.info("Routing file: {}", path);

        if (path.endsWith(".md") || path.contains(obsidianFolder)) {
            return "markdownChannel";
        } else if (path.contains(documentsFolder)) {
            return "unstructuredChannel";
        }

        log.warn("File ignored by ingestion pipeline (no matching route). File: {}", filename);
        return "nullChannel";
    }

    @Bean
    public IntegrationFlow markdownFlow(VectorStore vectorStore) {
        return IntegrationFlow.from(markdownChannel())
                .transform(Message.class, this::processMarkdownMessage)
                .handle((GenericHandler<List<Document>>) (payload, headers) -> {
                    documentService.removeOldDocuments(payload, vectorStore);
                    return payload;
                })
                .transform(documentService::splitDocuments)
                .split()
                .handle(msg -> {
                    Document doc = (Document) msg.getPayload();
                    vectorStore.add(List.of(doc));
                    log.info("Indexed markdown document: {}", doc.getId());
                })
                .get();
    }

    private List<Document> processMarkdownMessage(Message<?> message) {
        try (InputStream stream = (InputStream) message.getPayload()) {
            String filename = (String) message.getHeaders().get(FileHeaders.REMOTE_FILE);
            return ingestionService.processMarkdown(stream, filename != null ? filename : "unknown.md");
        } catch (Exception e) {
            throw new IngestionException("Error processing markdown stream", e);
        }
    }

    @Bean
    public IntegrationFlow unstructuredFlow(VectorStore vectorStore) {
        return IntegrationFlow.from(unstructuredChannel())
                .transform(Message.class, this::processUnstructuredMessage)
                .handle((GenericHandler<List<Document>>) (payload, headers) -> {
                    documentService.removeOldDocuments(payload, vectorStore);
                    return payload;
                })
                .transform(documentService::splitDocuments)
                .split()
                .handle(msg -> {
                    Document doc = (Document) msg.getPayload();
                    vectorStore.add(List.of(doc));
                    log.info("Indexed unstructured document: {}", doc.getId());
                })
                .get();
    }

    private List<Document> processUnstructuredMessage(Message<?> message) {
        try (InputStream stream = (InputStream) message.getPayload()) {
            String filename = (String) message.getHeaders().get(FileHeaders.REMOTE_FILE);
            return ingestionService.processUnstructured(stream, filename != null ? filename : "unknown");
        } catch (Exception e) {
            throw new IngestionException("Error processing unstructured stream", e);
        }
    }
}
