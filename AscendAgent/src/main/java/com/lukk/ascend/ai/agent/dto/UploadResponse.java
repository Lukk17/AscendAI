package com.lukk.ascend.ai.agent.dto;

import java.util.List;

public record UploadResponse(List<String> uploaded, List<String> failures) {
}
