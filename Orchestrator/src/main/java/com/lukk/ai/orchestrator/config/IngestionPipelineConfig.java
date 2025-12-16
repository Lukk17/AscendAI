package com.lukk.ai.orchestrator.config;

import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.text.TextContentRenderer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.integration.annotation.InboundChannelAdapter;
import org.springframework.integration.annotation.Poller;
import org.springframework.integration.annotation.ServiceActivator;
import org.springframework.integration.aws.inbound.S3InboundFileSynchronizingMessageSource;
import org.springframework.integration.aws.support.S3SessionFactory;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.config.EnableIntegration;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.file.FileReadingMessageSource;
import org.springframework.integration.file.filters.AcceptOnceFileListFilter;
import org.springframework.integration.file.filters.ChainFileListFilter;
import org.springframework.integration.file.filters.FileSystemPersistentAcceptOnceFileListFilter;
import org.springframework.integration.jdbc.metadata.JdbcMetadataStore;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessageHandler;
import org.springframework.util.StreamUtils;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;
import org.springframework.web.reactive.function.client.WebClient;

import javax.sql.DataSource;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@Configuration
@EnableIntegration
public class IngestionPipelineConfig {

    private static final Logger logger = LoggerFactory.getLogger(IngestionPipelineConfig.class);

    @Value("${app.ingestion.chunk-size:500}")
    private int chunkSize;

    @Value("${app.unstructured.base-url:http://localhost:9080}")
    private String unstructuredApiUrl;

    @Value("${s3.bucket}")
    private String s3Bucket;

    @Value("${s3.endpoint}")
    private String s3Endpoint;

    @Value("${s3.access-key}")
    private String s3AccessKey;

    @Value("${s3.secret-key}")
    private String s3SecretKey;

    @Bean
    public S3Client s3Client() {
        return S3Client.builder()
                .region(Region.US_EAST_1) // MinIO requires a region, US_EAST_1 is standard default
                .endpointOverride(URI.create(s3Endpoint))
                .credentialsProvider(StaticCredentialsProvider.create(
                        AwsBasicCredentials.create(s3AccessKey, s3SecretKey)))
                .forcePathStyle(true)
                .build();
    }

    @Bean
    public ConcurrentMetadataStore metadataStore(DataSource dataSource) {
        return new JdbcMetadataStore(dataSource);
    }

    @Bean
    @InboundChannelAdapter(value = "s3Channel", poller = @Poller(fixedDelay = "5000", errorChannel = "errorChannel"))
    public S3InboundFileSynchronizingMessageSource s3MessageSource(S3Client s3Client,
            ConcurrentMetadataStore metadataStore) {
        S3SessionFactory s3SessionFactory = new S3SessionFactory(s3Client);

        var synchronizer = new org.springframework.integration.aws.inbound.S3InboundFileSynchronizer(s3SessionFactory);
        synchronizer.setRemoteDirectory(s3Bucket);
        synchronizer.setDeleteRemoteFiles(false);
        synchronizer.setPreserveTimestamp(true);
        synchronizer
                .setFilter(new org.springframework.integration.aws.support.filters.S3PersistentAcceptOnceFileListFilter(
                        metadataStore, "s3-metadata-"));

        S3InboundFileSynchronizingMessageSource messageSource = new S3InboundFileSynchronizingMessageSource(
                synchronizer);
        messageSource.setLocalDirectory(new File("downloads"));
        messageSource.setAutoCreateLocalDirectory(true);

        // Filter for local files to avoid reprocessing
        ChainFileListFilter<File> localFilter = new ChainFileListFilter<>();
        localFilter.addFilter(new FileSystemPersistentAcceptOnceFileListFilter(metadataStore, "local-fs-metadata-"));
        messageSource.setLocalFilter(localFilter);

        return messageSource;
    }

    @Bean
    public MessageChannel s3Channel() {
        return new DirectChannel();
    }

    @Bean
    public IntegrationFlow ingestionFlow() {
        return IntegrationFlow.from(s3Channel())
                .route(File.class, file -> {
                    String path = file.getAbsolutePath();
                    if (path.contains("obsidian")) {
                        return "markdownChannel";
                    } else if (path.contains("documents")) {
                        return "unstructuredChannel";
                    }
                    return "nullChannel";
                })
                .get();
    }

    @Bean
    public IntegrationFlow markdownFlow(VectorStore vectorStore) {
        return IntegrationFlow.from("markdownChannel")
                .transform(File.class, this::processMarkdown)
                .transform(this::splitDocuments)
                .split()
                .handle(message -> {
                    Document doc = (Document) message.getPayload();
                    vectorStore.add(List.of(doc));
                    logger.info("Indexed markdown document: {}", doc.getId());
                })
                .get();
    }

    @Bean
    public IntegrationFlow unstructuredFlow(VectorStore vectorStore) {
        return IntegrationFlow.from("unstructuredChannel")
                .transform(File.class, this::processUnstructured)
                .transform(this::splitDocuments)
                .split()
                .handle(message -> {
                    Document doc = (Document) message.getPayload();
                    vectorStore.add(List.of(doc));
                    logger.info("Indexed structured document: {}", doc.getId());
                })
                .get();
    }

    @Bean
    public MessageChannel errorChannel() {
        DirectChannel channel = new DirectChannel();
        channel.subscribe(message -> logger.error("Error in ingestion pipeline: {}", message.getPayload()));
        return channel;
    }

    // --- Helpers ---

    private List<Document> processMarkdown(File file) {
        try (FileInputStream fis = new FileInputStream(file)) {
            String content = StreamUtils.copyToString(fis, StandardCharsets.UTF_8);

            // Simple parsing strategy: Use CommonMark to parse and extract text with
            // headers as metadata
            Parser parser = Parser.builder().build();
            Node document = parser.parse(content);
            TextContentRenderer renderer = TextContentRenderer.builder().build();
            String text = renderer.render(document);

            // In a real implementation, you'd iterate nodes to attach header metadata.
            // For now, we return one document with the content.
            return List.of(new Document(text, Map.of("source", file.getName(), "type", "markdown")));
        } catch (IOException e) {
            throw new RuntimeException("Failed to read markdown file", e);
        }
    }

    private List<Document> processUnstructured(File file) {
        WebClient webClient = WebClient.create(unstructuredApiUrl);

        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("files", new FileSystemResource(file));
        builder.part("strategy", "hi_res");

        // Call Unstructured API
        try {
            // Note: This is a simplified call. Real response parsing depends on
            // Unstructured API JSON format.
            // We assume it returns a list of elements.
            String response = webClient.post()
                    .uri("/general/v0/general")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .bodyValue(builder.build())
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            // Placeholder: Wrap response in a document.
            // Ideally we parse JSON, extract "text" fields and tables.
            return List.of(new Document(response, Map.of("source", file.getName(), "type", "unstructured")));

        } catch (Exception e) {
            throw new RuntimeException("Failed to call Unstructured API", e);
        }
    }

    private List<Document> splitDocuments(Object payload) {
        List<Document> docs = (List<Document>) payload;
        TokenTextSplitter splitter = new TokenTextSplitter(chunkSize, 30, 5, 10000, true);
        return splitter.apply(docs);
    }
}
