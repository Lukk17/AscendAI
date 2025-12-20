package com.lukk.ascend.ai.orchestrator.test;

import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import software.amazon.awssdk.services.s3.S3Client;

@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:testdb",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.jpa.database-platform=org.hibernate.dialect.H2Dialect",
        "spring.integration.jdbc.initialize-schema=always",
        "spring.ai.mcp.client.enabled=false"
})
public abstract class BaseIntegrationTest {

    @MockitoBean
    protected VectorStore vectorStore;

    @MockitoBean(name = "initVectorStore")
    protected CommandLineRunner initVectorStore;

    @MockitoBean
    protected ChatClient chatClient;

    @MockitoBean
    protected S3Client s3Client;
}
