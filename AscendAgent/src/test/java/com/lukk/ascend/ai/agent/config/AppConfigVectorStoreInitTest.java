package com.lukk.ascend.ai.agent.config;

import com.lukk.ascend.ai.agent.config.properties.VectorStoreProperties;
import io.qdrant.client.QdrantClient;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.boot.CommandLineRunner;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AppConfigVectorStoreInitTest {

    @Test
    @DisplayName("initVectorStore skips collection creation when it already exists")
    void initVectorStore_CollectionAlreadyExists_SkipsCreation() throws Exception {
        // given
        AppConfig config = buildConfig();
        QdrantClient qdrant = mock(QdrantClient.class);
        when(qdrant.listCollectionsAsync())
                .thenReturn(com.google.common.util.concurrent.Futures.immediateFuture(List.of("ascendai-768")));
        VectorStoreProperties props = new VectorStoreProperties();
        VectorStoreProperties.CollectionConfig col = new VectorStoreProperties.CollectionConfig();
        col.setName("ascendai-768");
        col.setSize(768);
        props.setCollections(List.of(col));

        // when
        CommandLineRunner runner = config.initVectorStore(qdrant, props);
        runner.run();

        // then
        verify(qdrant).listCollectionsAsync();
    }

    @Test
    @DisplayName("initVectorStore creates collection when it does not exist")
    void initVectorStore_CollectionDoesNotExist_CreatesCollection() throws Exception {
        // given
        AppConfig config = buildConfig();
        QdrantClient qdrant = mock(QdrantClient.class);
        when(qdrant.listCollectionsAsync())
                .thenReturn(com.google.common.util.concurrent.Futures.immediateFuture(List.of()));
        io.qdrant.client.grpc.Collections.CollectionOperationResponse successResponse =
                io.qdrant.client.grpc.Collections.CollectionOperationResponse.newBuilder().setResult(true).build();
        when(qdrant.createCollectionAsync(anyString(), any(io.qdrant.client.grpc.Collections.VectorParams.class)))
                .thenReturn(com.google.common.util.concurrent.Futures.immediateFuture(successResponse));
        VectorStoreProperties props = new VectorStoreProperties();
        VectorStoreProperties.CollectionConfig col = new VectorStoreProperties.CollectionConfig();
        col.setName("ascendai-768");
        col.setSize(768);
        props.setCollections(List.of(col));

        // when
        CommandLineRunner runner = config.initVectorStore(qdrant, props);
        runner.run();

        // then
        verify(qdrant).createCollectionAsync(anyString(), any(io.qdrant.client.grpc.Collections.VectorParams.class));
    }

    @Test
    @DisplayName("initVectorStore handles InterruptedException from listCollectionsAsync gracefully")
    void initVectorStore_ListCollectionsInterrupted_HandledGracefully() throws Exception {
        // given
        AppConfig config = buildConfig();
        QdrantClient qdrant = mock(QdrantClient.class);
        com.google.common.util.concurrent.ListenableFuture<List<String>> interruptedFuture =
                com.google.common.util.concurrent.Futures.immediateFailedFuture(new InterruptedException("thread interrupted"));
        when(qdrant.listCollectionsAsync()).thenReturn(interruptedFuture);
        VectorStoreProperties props = new VectorStoreProperties();
        props.setCollections(List.of());

        // then
        CommandLineRunner runner = config.initVectorStore(qdrant, props);
        runner.run();
    }

    @Test
    @DisplayName("initVectorStore handles ExecutionException from listCollectionsAsync gracefully")
    void initVectorStore_ListCollectionsExecutionException_HandledGracefully() throws Exception {
        // given
        AppConfig config = buildConfig();
        QdrantClient qdrant = mock(QdrantClient.class);
        com.google.common.util.concurrent.ListenableFuture<List<String>> failedFuture =
                com.google.common.util.concurrent.Futures.immediateFailedFuture(new RuntimeException("Qdrant down"));
        when(qdrant.listCollectionsAsync()).thenReturn(failedFuture);
        VectorStoreProperties props = new VectorStoreProperties();
        props.setCollections(List.of());

        // then
        CommandLineRunner runner = config.initVectorStore(qdrant, props);
        runner.run();
    }

    @Test
    @DisplayName("initVectorStore handles ExecutionException from createCollectionAsync gracefully")
    void initVectorStore_CreateCollectionExecutionException_HandledGracefully() throws Exception {
        // given
        AppConfig config = buildConfig();
        QdrantClient qdrant = mock(QdrantClient.class);
        when(qdrant.listCollectionsAsync())
                .thenReturn(com.google.common.util.concurrent.Futures.immediateFuture(List.of()));
        com.google.common.util.concurrent.ListenableFuture<io.qdrant.client.grpc.Collections.CollectionOperationResponse> failedCreate =
                com.google.common.util.concurrent.Futures.immediateFailedFuture(new RuntimeException("create failed"));
        when(qdrant.createCollectionAsync(anyString(), any(io.qdrant.client.grpc.Collections.VectorParams.class))).thenReturn(failedCreate);
        VectorStoreProperties props = new VectorStoreProperties();
        VectorStoreProperties.CollectionConfig col = new VectorStoreProperties.CollectionConfig();
        col.setName("new-collection");
        col.setSize(1536);
        props.setCollections(List.of(col));

        // then
        CommandLineRunner runner = config.initVectorStore(qdrant, props);
        runner.run();
    }


    private AppConfig buildConfig() {
        AppConfig config = new AppConfig();
        ReflectionTestUtils.setField(config, "connectTimeout", 30_000);
        ReflectionTestUtils.setField(config, "readTimeout", 120_000);
        ReflectionTestUtils.setField(config, "s3Endpoint", "http://localhost:9070");
        ReflectionTestUtils.setField(config, "s3PublicEndpoint", "http://localhost:9070");
        ReflectionTestUtils.setField(config, "s3AccessKey", "minioadmin");
        ReflectionTestUtils.setField(config, "s3SecretKey", "minioadmin");
        return config;
    }
}
