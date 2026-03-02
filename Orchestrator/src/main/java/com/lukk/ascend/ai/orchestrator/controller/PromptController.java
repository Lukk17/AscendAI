package com.lukk.ascend.ai.orchestrator.controller;

import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonErrorResponses;
import com.lukk.ascend.ai.orchestrator.config.api.ApiCommonSuccessResponses;
import com.lukk.ascend.ai.orchestrator.dto.AiResponse;
import com.lukk.ascend.ai.orchestrator.service.ChatOrchestratorService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@Slf4j
@RestController
@RequiredArgsConstructor
@Tag(name = "Prompt", description = "Prompt controller.")
@RequestMapping(value = "/api/v1/ai", produces = "application/json")
public class PromptController {

    private final ChatOrchestratorService chatOrchestratorService;

    @Value("${app.user.default-id:user1}")
    private String defaultUserId;

    @Operation(summary = "AscendAI prompt endpoint", description = "Process user prompt with AI, supporting optional image and document context.")
    @ApiCommonSuccessResponses
    @ApiCommonErrorResponses
    @PostMapping(value = "/prompt", consumes = "multipart/form-data")
    public ResponseEntity<AiResponse> prompt(
            @RequestParam("prompt") String prompt,
            @RequestParam(value = "image", required = false) MultipartFile image,
            @RequestParam(value = "document", required = false) MultipartFile document,
            @RequestParam(value = "provider", required = false) String provider,
            @RequestParam(value = "model", required = false) String model,
            @RequestHeader(value = "X-User-Id", required = false) String userIdHeader) {

        String userId = userIdHeader != null && !userIdHeader.isBlank() ? userIdHeader : defaultUserId;

        log.info("Received Prompt | ClientID: {} | Provider: {} | Model: {} | HasImage: {} | HasDoc: {} | Prompt: {}",
                userId,
                provider,
                model,
                image != null && !image.isEmpty(),
                document != null && !document.isEmpty(),
                prompt);
        return ResponseEntity.ok(chatOrchestratorService.prompt(prompt, image, document, userId, provider, model));
    }
}
