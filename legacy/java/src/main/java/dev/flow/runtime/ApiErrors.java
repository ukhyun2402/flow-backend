package dev.flow.runtime;

import dev.flow.core.FlowFault;
import java.util.Map;
import org.springframework.http.*;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.annotation.*;

@RestControllerAdvice
public class ApiErrors {

    @ExceptionHandler(org.springframework.web.servlet.resource.NoResourceFoundException.class)
    public ResponseEntity<?> missing(Exception e) {
        return ResponseEntity.status(404).body(
            Map.of("code", "NOT_FOUND", "message", "Route not found")
        );
    }

    @ExceptionHandler(FlowFault.class)
    public ResponseEntity<?> flow(FlowFault e) {
        return ResponseEntity.status(e.status()).body(
            Map.of("code", e.code(), "message", e.getMessage())
        );
    }

    @ExceptionHandler({ HttpMessageNotReadableException.class, IllegalArgumentException.class })
    public ResponseEntity<?> input(Exception e) {
        return ResponseEntity.badRequest().body(
            Map.of("code", "VALIDATION_ERROR", "message", "Invalid request")
        );
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<?> other(Exception e) {
        return ResponseEntity.internalServerError().body(
            Map.of("code", "INTERNAL_ERROR", "message", "Operation failed")
        );
    }
}
