package com.lukk.ascend.ai.orchestrator.config.api;

import io.swagger.v3.oas.annotations.responses.ApiResponse;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

@Target({ElementType.METHOD, ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@ApiResponse(responseCode = "200", description = "Successful operation")
@ApiResponse(responseCode = "201", description = "Resource created")
@ApiResponse(responseCode = "202", description = "Request accepted for processing")
@ApiResponse(responseCode = "204", description = "No content")
public @interface ApiCommonSuccessResponses {
}
