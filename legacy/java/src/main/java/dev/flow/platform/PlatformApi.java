package dev.flow.platform;

import com.fasterxml.jackson.databind.*;
import dev.flow.core.*;
import dev.flow.db.Databases;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Connection;
import java.util.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
@ConditionalOnProperty(name = "flow.mode", havingValue = "platform", matchIfMissing = true)
public class PlatformApi {

    public record Preview(Flow flow, JsonNode input, String executionId) {}

    public record SqlPreview(
        String databaseRef,
        String sql,
        JsonNode parameters,
        boolean command,
        String executionId
    ) {}

    private final Validator validator;
    private final Engine engine;
    private final Repository repository;
    private final Generator generator;
    private final Databases databases;

    public PlatformApi(
        Validator validator,
        Engine engine,
        Repository repository,
        Generator generator,
        Databases databases
    ) {
        this.validator = validator;
        this.engine = engine;
        this.repository = repository;
        this.generator = generator;
        this.databases = databases;
    }

    @GetMapping("/flows")
    public Object list() throws Exception {
        return repository.list();
    }

    @GetMapping("/history")
    public Object history() throws Exception {
        return repository.history("audit.jsonl");
    }

    @GetMapping("/executions/{id}")
    public Object traces(@PathVariable String id) throws Exception {
        UUID.fromString(id);
        return repository
            .history("traces.jsonl")
            .stream()
            .filter(t -> t.path("executionId").asText().equals(id))
            .toList();
    }

    @GetMapping("/flows/{id}/{revision}")
    public Flow get(@PathVariable String id, @PathVariable int revision) throws Exception {
        return repository.get(id, revision);
    }

    @PostMapping("/validate")
    public Object validate(@RequestBody Flow flow) {
        var issues = validator.validate(flow);
        return Map.of("valid", issues.isEmpty(), "issues", issues);
    }

    @PostMapping("/flows")
    public Object save(@RequestBody Flow flow, HttpServletRequest request) throws Exception {
        Access.require(request, "admin", "editor");
        validator.plan(flow);
        repository.save(flow);
        return Map.of("id", flow.id(), "revision", flow.revision());
    }

    @PostMapping("/preview")
    public Engine.Result preview(@RequestBody Preview body, HttpServletRequest request)
        throws Exception {
        Access.require(request, "admin", "runner");
        var plan = validator.plan(body.flow());
        repository.audit("PREVIEW_STARTED", body.flow().id(), body.flow().revision());
        Engine.Result result = engine.run(
            plan,
            body.input(),
            true,
            body.executionId() == null ? UUID.randomUUID().toString() : body.executionId()
        );
        repository.trace(result.trace());
        return result;
    }

    @PostMapping("/generate")
    public ResponseEntity<byte[]> generate(@RequestBody Flow flow, HttpServletRequest request)
        throws Exception {
        Access.require(request, "admin");
        byte[] zip = generator.generate(flow);
        repository.audit("SERVER_GENERATED", flow.id(), flow.revision());
        return ResponseEntity.ok()
            .header("Content-Disposition", "attachment; filename=\"generated-server.zip\"")
            .contentType(MediaType.parseMediaType("application/zip"))
            .body(zip);
    }

    @PostMapping("/databases/{id}/test")
    public Object connection(@PathVariable String id, HttpServletRequest request) throws Exception {
        Access.require(request, "admin");
        try (Connection c = databases.connect(id)) {
            return Map.of(
                "connected",
                c.isValid(5),
                "database",
                c.getMetaData().getDatabaseProductName(),
                "version",
                c.getMetaData().getDatabaseProductVersion()
            );
        }
    }

    @GetMapping("/databases/{id}/metadata")
    public Object metadata(@PathVariable String id, HttpServletRequest request) throws Exception {
        Access.require(request, "admin", "runner");
        return databases.metadata(id);
    }

    @PostMapping("/executions/{id}/cancel")
    public Object cancel(@PathVariable String id, HttpServletRequest request) throws Exception {
        Access.require(request, "admin", "runner");
        UUID.fromString(id);
        boolean cancelled = databases.cancel(id);
        repository.audit("CANCEL_REQUESTED", id, 0);
        return Map.of("cancelRequested", cancelled);
    }

    @PostMapping("/sql/preview")
    public Object sql(@RequestBody SqlPreview body, HttpServletRequest request) throws Exception {
        Access.require(request, "admin", "runner");
        if (
            body.command() && !databases.previewCommandAllowed(body.databaseRef())
        ) throw new FlowFault("FORBIDDEN", 403, "Write preview requires a verified test database");
        repository.audit("SQL_PREVIEW_STARTED", body.databaseRef(), 0);
        try (Connection c = databases.connect(body.databaseRef())) {
            c.setAutoCommit(false);
            String executionId =
                body.executionId() == null ? UUID.randomUUID().toString() : body.executionId();
            UUID.fromString(executionId);
            try {
                return databases.execute(
                    c,
                    body.sql(),
                    body.parameters(),
                    body.command(),
                    100,
                    5_000_000,
                    10,
                    executionId
                );
            } finally {
                c.rollback();
            }
        }
    }
}
