package com.lukk.ascend.ai.orchestrator.config.api;

import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.responses.ApiResponse;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

@Target({ElementType.METHOD, ElementType.TYPE})
@Retention(RetentionPolicy.RUNTIME)
@ApiResponse(responseCode = "400", description = "Bad Request - Invalid parameters", content = @Content(mediaType = "application/json"))
@ApiResponse(responseCode = "401", description = "Unauthorized - Not authorized to access this resource", content = @Content(mediaType = "application/json"))
@ApiResponse(responseCode = "500", description = "Internal Server Error - Something went wrong", content = @Content(mediaType = "application/json"))
public @interface ApiCommonErrorResponses {
}
