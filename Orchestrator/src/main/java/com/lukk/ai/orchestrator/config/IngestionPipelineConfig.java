package com.lukk.ai.orchestrator.config;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.commonmark.node.AbstractVisitor;
import org.commonmark.node.Node;
import org.commonmark.parser.Parser;
import org.commonmark.renderer.text.TextContentRenderer;
import org.springframework.ai.document.Document;
import org.springframework.ai.transformer.splitter.TokenTextSplitter;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.Filter;
import org.springframework.ai.vectorstore.filter.FilterExpressionBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.integration.annotation.InboundChannelAdapter;
import org.springframework.integration.annotation.Poller;
import org.springframework.integration.aws.inbound.S3InboundFileSynchronizingMessageSource;
import org.springframework.integration.aws.support.S3SessionFactory;
import org.springframework.integration.channel.DirectChannel;
import org.springframework.integration.config.EnableIntegration;
import org.springframework.integration.core.GenericHandler;
import org.springframework.integration.dsl.IntegrationFlow;
import org.springframework.integration.file.filters.ChainFileListFilter;
import org.springframework.integration.file.filters.FileSystemPersistentAcceptOnceFileListFilter;
import org.springframework.integration.jdbc.metadata.JdbcMetadataStore;
import org.springframework.integration.metadata.ConcurrentMetadataStore;
import org.springframework.messaging.MessageChannel;
import org.springframework.util.StreamUtils;
import org.springframework.web.reactive.function.client.WebClient;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.S3Client;

import javax.sql.DataSource;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

@Configuration
@EnableIntegration
@Slf4j
public class IngestionPipelineConfig {

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
    public org.springframework.boot.CommandLineRunner initBucket(S3Client s3Client) {
        return args -> {
            try {
                s3Client.headBucket(
                        software.amazon.awssdk.services.s3.model.HeadBucketRequest.builder().bucket(s3Bucket).build());
                log.info("Bucket '{}' already exists.", s3Bucket);
            } catch (software.amazon.awssdk.services.s3.model.NoSuchBucketException e) {
                log.info("Bucket '{}' not found. Creating...", s3Bucket);
                s3Client.createBucket(software.amazon.awssdk.services.s3.model.CreateBucketRequest.builder()
                        .bucket(s3Bucket).build());
                log.info("Bucket '{}' created successfully.", s3Bucket);
            } catch (Exception e) {
                log.error("Failed to check/create bucket '{}'", s3Bucket, e);
            }
        };
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
                .handle((GenericHandler<List<Document>>) (payload, headers) -> {
                    removeOldDocuments(payload, vectorStore);
                    return payload;
                })
                .transform(this::splitDocuments)
                .split()
                .handle(message -> {
                    Document doc = (Document) message.getPayload();
                    vectorStore.add(List.of(doc));
                    log.info("Indexed markdown document: {}", doc.getId());
                })
                .get();
    }

    @Bean
    public IntegrationFlow unstructuredFlow(VectorStore vectorStore) {
        return IntegrationFlow.from("unstructuredChannel")
                .transform(File.class, this::processUnstructured)
                .handle((GenericHandler<List<Document>>) (payload, headers) -> {
                    removeOldDocuments(payload, vectorStore);
                    return payload;
                })
                .transform(this::splitDocuments)
                .split()
                .handle(message -> {
                    Document doc = (Document) message.getPayload();
                    vectorStore.add(List.of(doc));
                    log.info("Indexed structured document: {}", doc.getId());
                })
                .get();
    }

    @Bean
    public MessageChannel errorChannel() {
        DirectChannel channel = new DirectChannel();
        channel.subscribe(message -> log.error("Error in ingestion pipeline: {}", message.getPayload()));
        return channel;
    }

    private void removeOldDocuments(List<Document> newDocuments, VectorStore vectorStore) {
        if (newDocuments.isEmpty()) {
            return;
        }
        String source = (String) newDocuments.get(0).getMetadata().get("source");
        if (source != null) {
            log.info("Removing existing documents for source: {}", source);
            Filter.Expression filterExpression = new FilterExpressionBuilder()
                    .eq("source", source)
                    .build();

            vectorStore.delete(filterExpression);
            log.info("Deleted old documents for source: {}", source);
        }
    }

    private List<Document> processMarkdown(File file) {
        log.info("Processing file: {}, Last Modified: {}", file.getName(), new java.util.Date(file.lastModified()));
        try (FileInputStream fis = new FileInputStream(file)) {
            String content = StreamUtils.copyToString(fis, StandardCharsets.UTF_8);

            Parser parser = Parser.builder().build();
            Node document = parser.parse(content);

            // This is a simple visitor to find the first H1 as a title.
            // For production, a file can be split per each header, not just one per file as title.
            final String[] title = {file.getName()}; // Default to filename
            document.accept(new AbstractVisitor() {
                @Override
                public void visit(org.commonmark.node.Heading heading) {
                    if (heading.getLevel() == 1 && title[0].equals(file.getName())) {
                        TextContentRenderer renderer = TextContentRenderer.builder().build();
                        title[0] = renderer.render(heading);
                    }
                    super.visit(heading);
                }
            });

            TextContentRenderer renderer = TextContentRenderer.builder().build();
            String text = renderer.render(document);

            Map<String, Object> metadata = new java.util.HashMap<>();
            metadata.put("source", file.getName());
            metadata.put("type", "markdown");
            metadata.put("title", title[0]);
            metadata.put("last_modified", new java.util.Date(file.lastModified()).toString());

            return List.of(new Document(text, metadata));
        } catch (IOException e) {
            throw new RuntimeException("Failed to read markdown file", e);
        } finally {
            if (file.exists()) {
                boolean deleted = file.delete();
                log.info("Local file '{}' deleted: {}", file.getName(), deleted);
            }
        }
    }

    private List<Document> processUnstructured(File file) {
        log.info("Processing file: {}, Last Modified: {}", file.getName(), new java.util.Date(file.lastModified()));
        WebClient webClient = WebClient.create(unstructuredApiUrl);

        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("files", new FileSystemResource(file));
        builder.part("strategy", "hi_res");

        try {
            String responseJson = webClient.post()
                    .uri("/general/v0/general")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .bodyValue(builder.build())
                    .retrieve()
                    .bodyToMono(String.class)
                    .block();

            ObjectMapper mapper = new ObjectMapper();
            JsonNode rootNode = mapper.readTree(responseJson);

            StringBuilder fullText = new StringBuilder();
            if (rootNode.isArray()) {
                for (JsonNode node : rootNode) {
                    if (node.has("text")) {
                        fullText.append(node.get("text").asText()).append("\n\n");
                    }
                }
            } else {
                if (rootNode.has("text")) {
                    fullText.append(rootNode.get("text").asText());
                }
            }

            Map<String, Object> metadata = new java.util.HashMap<>();
            metadata.put("source", file.getName());
            metadata.put("type", "unstructured");
            metadata.put("last_modified", new java.util.Date(file.lastModified()).toString());

            return List.of(new Document(fullText.toString(), metadata));

        } catch (Exception e) {
            throw new RuntimeException("Failed to call Unstructured API or parse response", e);
        } finally {
            if (file.exists()) {
                boolean deleted = file.delete();
                log.info("Local file '{}' deleted: {}", file.getName(), deleted);
            }
        }
    }

    @SuppressWarnings("unchecked")
    private List<Document> splitDocuments(Object payload) {
        List<Document> docs = (List<Document>) payload;
        TokenTextSplitter splitter = new TokenTextSplitter(chunkSize, 30, 5, 10000, true);
        return splitter.apply(docs);
    }
}
