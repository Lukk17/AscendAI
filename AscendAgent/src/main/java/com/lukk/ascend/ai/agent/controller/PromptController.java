package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.agent.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.service.AscendChatService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Prompt", description = "Prompt controller.")
@RequestMapping(value = "/api/v1/ai", produces = "application/json")
public class PromptController {

    private final AscendChatService ascendChatService;

    @Value("${app.user.default-id:user1}")
    private String defaultUserId;

    @Operation(
            summary = "AscendAI prompt endpoint",
            description = "Process user prompt with AI, supporting optional image/document context and per-request AI provider/model selection."
    )
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/prompt", consumes = "multipart/form-data")
    public ResponseEntity<AiResponse> prompt(
            @Parameter(description = "User prompt text", required = true, example = "What is the weather in Warsaw?")
            @RequestParam("prompt") String prompt,

            @Parameter(description = "Optional image file for vision-capable models")
            @RequestParam(value = "image", required = false) MultipartFile image,

            @Parameter(description = "Optional document file to include as context")
            @RequestParam(value = "document", required = false) MultipartFile document,

            @Parameter(description = "AI provider name. Available: lmstudio, openai, gemini, anthropic, minimax. "
                    + "Defaults to app.ai.default-provider from config. "
                    + "Note: lmstudio chat is incompatible with openai embeddings, and openai chat is incompatible with lmstudio/gemini embeddings. "
                    + "Returns 400 if incompatible with the selected embeddingProvider.",
                    example = "anthropic")
            @RequestParam(value = "provider", required = false) String provider,

            @Parameter(description = "Model override for the selected provider. If omitted, uses the provider's default model. Examples per provider: openai=gpt-5.1, gpt-5.4 | anthropic=claude-sonnet-4-6, claude-opus-4-6 | gemini=gemini-3.1-pro, gemini-2.5-flash | minimax=MiniMax-M2.5, MiniMax-M2.1",
                    example = "claude-sonnet-4-6")
            @RequestParam(value = "model", required = false) String model,

            @Parameter(description = "Embedding provider for RAG similarity search. Available: lmstudio (768-dim), gemini (768-dim), openai (1536-dim). "
                    + "Defaults to EMBEDDING_PROVIDER env var (lmstudio). "
                    + "Must be compatible with the chat provider — lmstudio↔openai combinations return 400.",
                    example = "lmstudio")
            @RequestParam(value = "embeddingProvider", required = false) String embeddingProvider,

            @Parameter(description = "User identifier for chat history and memory. Defaults to app.user.default-id from config.",
                    example = "user1")
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader) {

        String userId = userIdHeader != null && !userIdHeader.isBlank() ? userIdHeader : defaultUserId;

        log.info("Received Prompt | ClientID: {} | Provider: {} | Model: {} | EmbeddingProvider: {} | HasImage: {} | HasDoc: {} | Prompt: {}",
                userId,
                provider,
                model,
                embeddingProvider,
                image != null && !image.isEmpty(),
                document != null && !document.isEmpty(),
                prompt);
        return ResponseEntity.ok(ascendChatService.prompt(prompt, image, document, userId, provider, model, embeddingProvider));
    }
}
