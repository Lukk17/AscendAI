package com.lukk.ascend.ai.agent.controller;

import com.lukk.ascend.ai.agent.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.agent.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.agent.config.properties.AiProviderProperties;
import com.lukk.ascend.ai.agent.dto.AiResponse;
import com.lukk.ascend.ai.agent.memory.CompactionOverride;
import com.lukk.ascend.ai.agent.service.AscendChatService;
import com.lukk.ascend.ai.agent.service.VisionCapabilityResolver;
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
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Prompt", description = "Prompt controller.")
@RequestMapping(value = "/api/v1/ai", produces = "application/json")
public class PromptController {

    private final AscendChatService ascendChatService;
    private final VisionCapabilityResolver visionCapabilityResolver;
    private final AiProviderProperties aiProviderProperties;

    @Value("${app.user.default-id:user1}")
    private String defaultUserId;

    @Operation(
            summary = "AscendAI prompt endpoint",
            description = "Process user prompt with AI, supporting optional image/document context and per-request AI provider/model selection."
    )
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/prompt", consumes = "multipart/form-data")
    public ResponseEntity<?> prompt(
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

            @Parameter(description = "If true, the response includes presigned download URLs for the source documents that grounded the RAG answer. Defaults to false.",
                    example = "false")
            @RequestParam(value = "attachSources", required = false) Boolean attachSources,

            @Parameter(description = "Provider used for the async chat-history compaction call. Defaults to the request's `provider`. Must match a configured provider key.",
                    example = "openai")
            @RequestParam(value = "compactionProvider", required = false) String compactionProvider,

            @Parameter(description = "Model override for the async chat-history compaction call. Defaults to the per-provider entry under app.memory.chat-history.compaction.provider-defaults.",
                    example = "gpt-4o-mini")
            @RequestParam(value = "compactionModel", required = false) String compactionModel,

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

        if (image != null && !image.isEmpty() && !visionCapabilityResolver.supportsImages(provider, model)) {
            com.lukk.ascend.ai.agent.dto.ApiError body = new com.lukk.ascend.ai.agent.dto.ApiError(
                    HttpStatus.UNSUPPORTED_MEDIA_TYPE.value(),
                    "vision_unsupported",
                    "Selected provider/model does not support image input. " +
                            "Use a vision-capable model (e.g. claude-sonnet-4-6, gpt-4o, gemini-2.5-pro).");
            return ResponseEntity.status(HttpStatus.UNSUPPORTED_MEDIA_TYPE).body(body);
        }

        if (compactionProvider != null && !compactionProvider.isBlank()
                && !aiProviderProperties.getProviders().containsKey(compactionProvider)) {
            com.lukk.ascend.ai.agent.dto.ApiError body = new com.lukk.ascend.ai.agent.dto.ApiError(
                    HttpStatus.BAD_REQUEST.value(),
                    "unknown_compaction_provider",
                    "compactionProvider '" + compactionProvider + "' is not configured. Known providers: "
                            + aiProviderProperties.getProviders().keySet());
            return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body);
        }

        boolean attach = attachSources != null && attachSources;
        CompactionOverride override = new CompactionOverride(compactionProvider, compactionModel);
        return ResponseEntity.ok(ascendChatService.prompt(prompt, image, document, userId, provider, model,
                embeddingProvider, attach, override));
    }
}
