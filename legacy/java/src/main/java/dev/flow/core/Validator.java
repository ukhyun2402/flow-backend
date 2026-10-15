package dev.flow.core;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.*;

public final class Validator {

    private static final com.fasterxml.jackson.databind.ObjectMapper JSON =
        new com.fasterxml.jackson.databind.ObjectMapper();
    private static final JsonNode SCHEMA;

    static {
        try (var in = Validator.class.getResourceAsStream("/flow.schema.json")) {
            SCHEMA = JSON.readTree(in);
        } catch (Exception ex) {
            throw new ExceptionInInitializerError(ex);
        }
    }

    public record Issue(String code, String flowId, String nodeId, String field, String message) {}

    public record Plan(
        Flow flow,
        Map<String, Flow.Node> nodes,
        Map<String, Map<String, String>> next
    ) {}

    private static final Set<String> TYPES = Set.of(
        "trigger.http",
        "validate",
        "transform",
        "branch",
        "db.query",
        "db.command",
        "http.call",
        "transaction.begin",
        "transaction.commit",
        "transaction.rollback",
        "error.raise",
        "response.http"
    );

    public List<Issue> validate(Flow f) {
        List<Issue> errors = new ArrayList<>();
        if (f == null) {
            errors.add(new Issue("FLOW_INVALID", null, null, "flow", "Flow required"));
            return errors;
        }
        try {
            Contracts.check(SCHEMA, JSON.valueToTree(f));
        } catch (FlowFault ex) {
            add(errors, f, null, "flow", "Flow does not satisfy flow.schema.json");
            return errors;
        }
        if (!"1.0".equals(f.specVersion())) add(
            errors,
            f,
            null,
            "specVersion",
            "Unsupported specification version"
        );
        if (
            f.id() == null ||
            !f.id().matches("[a-zA-Z0-9_-]{1,80}") ||
            f.revision() < 1 ||
            f.name() == null
        ) add(errors, f, null, "id", "Valid ID, name and positive revision required");
        if (
            f.inputSchema() == null ||
            f.outputSchema() == null ||
            f.resources() == null ||
            f.settings() == null
        ) add(errors, f, null, "schemas", "Schemas, resources and settings required");
        if (
            f.nodes() == null ||
            f.edges() == null ||
            f.nodes().isEmpty() ||
            f.nodes().size() > 500 ||
            f.edges().size() > 1500
        ) {
            add(errors, f, null, "nodes", "Require 1–500 nodes and at most 1500 edges");
            return errors;
        }
        Map<String, Flow.Node> nodes = new LinkedHashMap<>();
        for (Flow.Node n : f.nodes()) {
            if (
                n == null ||
                n.id() == null ||
                !n.id().matches("[a-zA-Z0-9_-]{1,80}") ||
                nodes.putIfAbsent(n.id(), n) != null
            ) {
                add(errors, f, null, "nodes", "Invalid or duplicate node ID");
                continue;
            }
            if (
                !TYPES.contains(n.type() == null ? "" : n.type()) ||
                n.name() == null ||
                n.config() == null ||
                !n.config().isObject()
            ) {
                add(errors, f, n.id(), "type", "Invalid node type, name or config");
                continue;
            }
            JsonNode c = n.config();
            String required = switch (n.type()) {
                case "trigger.http" -> "path";
                case "branch" -> "condition";
                case "db.query", "db.command" -> "sql";
                case "transaction.begin" -> "databaseRef";
                case "http.call" -> "serviceRef";
                case "error.raise" -> "code";
                case "response.http" -> "status";
                case "validate" -> "schema";
                case "transform" -> "mapping";
                default -> null;
            };
            if (required != null && !c.has(required)) add(
                errors,
                f,
                n.id(),
                "config." + required,
                "Required configuration missing"
            );
            if (n.type().startsWith("db.") || n.type().equals("transaction.begin")) {
                String db = c.path("databaseRef").asText();
                boolean found = false;
                if (f.resources() != null) for (JsonNode ref : f.resources().path("databases"))
                    found |= ref.asText().equals(db);
                if (!found) add(
                    errors,
                    f,
                    n.id(),
                    "config.databaseRef",
                    "Database resource is not declared"
                );
            }
            if (n.type().startsWith("db.")) try {
                dev.flow.db.SqlPolicy.check(c.path("sql").asText(), n.type().equals("db.command"));
            } catch (RuntimeException ex) {
                add(errors, f, n.id(), "config.sql", "Only one supported SQL statement is allowed");
            }
            if (
                n.type().equals("db.query") &&
                c.has("resultMode") &&
                !Set.of("many", "zeroOrOne").contains(c.path("resultMode").asText())
            ) add(errors, f, n.id(), "config.resultMode", "Unsupported result mode");
            if (
                n.type().equals("transaction.begin") &&
                c.has("isolation") &&
                !Set.of("READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE").contains(
                    c.path("isolation").asText()
                )
            ) add(errors, f, n.id(), "config.isolation", "Unsupported isolation level");
            if (n.type().equals("http.call")) {
                boolean found = false;
                for (JsonNode ref : f.resources().path("services"))
                    found |= ref.asText().equals(c.path("serviceRef").asText());
                if (!found) add(
                    errors,
                    f,
                    n.id(),
                    "config.serviceRef",
                    "Service resource is not declared"
                );
            }
            if (
                n.type().equals("response.http") &&
                (c.path("status").asInt() < 200 || c.path("status").asInt() > 599)
            ) add(errors, f, n.id(), "config.status", "Invalid HTTP response status");
            if (
                n.type().equals("trigger.http") &&
                (!Set.of("GET", "POST", "PUT", "PATCH", "DELETE").contains(
                    c.path("method").asText()
                ) ||
                    !c.path("path").asText().matches("/[a-zA-Z0-9_/{}/-]*") ||
                    c.path("path").asText().startsWith("/api/"))
            ) add(errors, f, n.id(), "config", "Invalid HTTP method or path");
            try {
                Contracts.rejectRemote(c);
            } catch (FlowFault ex) {
                add(errors, f, n.id(), "config", ex.getMessage());
            }
        }
        List<Flow.Node> starts = nodes
            .values()
            .stream()
            .filter(n -> "trigger.http".equals(n.type()))
            .toList();
        if (starts.size() != 1) add(errors, f, null, "nodes", "Exactly one HTTP trigger required");
        Map<String, Map<String, String>> next = new HashMap<>();
        for (Flow.Edge e : f.edges()) {
            if (e == null || !nodes.containsKey(e.from()) || !nodes.containsKey(e.to())) {
                add(errors, f, null, "edges", "Unknown edge endpoint");
                continue;
            }
            String t = nodes.get(e.from()).type();
            Set<String> ports = "response.http".equals(t)
                ? Set.of()
                : "branch".equals(t)
                  ? Set.of("true", "false", "error")
                  : "error.raise".equals(t)
                    ? Set.of("error")
                    : Set.of("success", "error");
            if (
                !ports.contains(e.port() == null ? "" : e.port()) ||
                next
                    .computeIfAbsent(e.from(), k -> new HashMap<>())
                    .putIfAbsent(e.port(), e.to()) != null
            ) add(errors, f, e.from(), "edges", "Invalid port or multiple edges on a port");
        }
        try {
            if (f.inputSchema() != null) Contracts.rejectRemote(f.inputSchema());
            if (f.outputSchema() != null) Contracts.rejectRemote(f.outputSchema());
        } catch (FlowFault ex) {
            add(errors, f, null, "schemas", ex.getMessage());
        }
        if (!errors.isEmpty()) return errors;
        for (Flow.Node n : nodes.values())
            try {
                JsonNode c = n.config();
                if (
                    n.type().equals("branch") &&
                    !ExpressionTypes.compatible(
                        ExpressionTypes.infer(c.get("condition"), f, nodes, new HashSet<>(), 0),
                        "boolean"
                    )
                ) add(errors, f, n.id(), "config.condition", "Branch condition must be boolean");
                for (String field : List.of("mapping", "body", "parameters", "value"))
                    if (c.has(field)) ExpressionTypes.infer(
                        c.get(field),
                        f,
                        nodes,
                        new HashSet<>(),
                        0
                    );
                if (n.type().equals("response.http")) {
                    String type = ExpressionTypes.infer(
                        c.get("body"),
                        f,
                        nodes,
                        new HashSet<>(),
                        0
                    );
                    if (
                        !ExpressionTypes.compatible(
                            type,
                            f.outputSchema().path("type").asText("unknown")
                        )
                    ) add(
                        errors,
                        f,
                        n.id(),
                        "config.body",
                        "Response type does not match output schema"
                    );
                }
                if (n.type().startsWith("db.")) {
                    var parsed =
                        org.springframework.jdbc.core.namedparam.NamedParameterUtils.parseSqlStatement(
                            c.path("sql").asText()
                        );
                    var source =
                        new org.springframework.jdbc.core.namedparam.MapSqlParameterSource();
                    c.path("parameters")
                        .fieldNames()
                        .forEachRemaining(k -> source.addValue(k, null));
                    org.springframework.jdbc.core.namedparam.NamedParameterUtils.buildValueArray(
                        parsed,
                        source,
                        null
                    );
                }
            } catch (RuntimeException ex) {
                add(
                    errors,
                    f,
                    n.id(),
                    "config",
                    ex instanceof FlowFault ? ex.getMessage() : "Missing SQL parameter mapping"
                );
            }
        if (!errors.isEmpty()) return errors;
        Set<String> reached = new HashSet<>();
        int[] budget = { 20000 };
        walk(
            f,
            starts.get(0).id(),
            nodes,
            next,
            new HashSet<>(),
            new HashSet<>(),
            null,
            reached,
            errors,
            budget
        );
        for (String id : nodes.keySet())
            if (!reached.contains(id)) add(errors, f, id, "nodes", "Unreachable node");
        return errors.stream().distinct().toList();
    }

    private void walk(
        Flow f,
        String id,
        Map<String, Flow.Node> nodes,
        Map<String, Map<String, String>> next,
        Set<String> stack,
        Set<String> outputs,
        String tx,
        Set<String> reached,
        List<Issue> errors,
        int[] budget
    ) {
        if (--budget[0] < 0) {
            if (budget[0] == -1) add(errors, f, id, "edges", "Path analysis limit exceeded");
            return;
        }
        if (!stack.add(id)) {
            add(errors, f, id, "edges", "Cycle detected");
            return;
        }
        reached.add(id);
        Flow.Node n = nodes.get(id);
        JsonNode c = n.config();
        references(c, outputs, f, id, errors);
        String after = tx;
        switch (n.type()) {
            case "transaction.begin" -> {
                if (tx != null) add(errors, f, id, "config", "Nested transaction");
                after = c.path("databaseRef").asText();
            }
            case "transaction.commit", "transaction.rollback" -> {
                if (tx == null) add(errors, f, id, "config", "No active transaction");
                after = null;
            }
            case "db.query", "db.command" -> {
                if (tx != null && !tx.equals(c.path("databaseRef").asText())) add(
                    errors,
                    f,
                    id,
                    "config",
                    "Transaction database mismatch"
                );
            }
            case "http.call" -> {
                if (tx != null) add(
                    errors,
                    f,
                    id,
                    "config",
                    "HTTP calls inside transactions are forbidden"
                );
            }
            case "response.http" -> {
                if (tx != null) add(errors, f, id, "config", "Response with active transaction");
            }
        }
        Map<String, String> edges = next.getOrDefault(id, Map.of());
        if (
            n.type().equals("branch") && (!edges.containsKey("true") || !edges.containsKey("false"))
        ) add(errors, f, id, "edges", "Both branch paths required");
        if (
            !Set.of("response.http", "error.raise", "branch").contains(n.type()) &&
            !edges.containsKey("success")
        ) add(errors, f, id, "edges", "Normal path must end in a response");
        for (var edge : edges.entrySet()) {
            Set<String> available = new HashSet<>(outputs);
            if (!edge.getKey().equals("error")) available.add(id);
            // Error handlers see pre-node state; failed commit/rollback state is not safe to continue.
            if (edge.getKey().equals("error") && n.type().startsWith("transaction.")) add(
                errors,
                f,
                id,
                "edges",
                "Transaction node error handlers are unsupported"
            );
            walk(
                f,
                edge.getValue(),
                nodes,
                next,
                new HashSet<>(stack),
                available,
                edge.getKey().equals("error") ? tx : after,
                reached,
                errors,
                budget
            );
        }
    }

    private void references(
        JsonNode c,
        Set<String> available,
        Flow f,
        String id,
        List<Issue> errors
    ) {
        if (c.isObject() && c.has("literal")) return;
        if (c.isObject() && c.has("ref")) {
            String ref = c.get("ref").asText();
            String[] parts = ref.split("\\.");
            if (
                ref.startsWith("nodes.") &&
                (parts.length < 3 || !parts[2].equals("output") || !available.contains(parts[1]))
            ) add(errors, f, id, "config", "Output reference is not guaranteed on this path");
            else if (
                !ref.startsWith("nodes.") &&
                !ref.startsWith("input.") &&
                !Set.of("context.requestId", "context.startedAt").contains(ref)
            ) add(errors, f, id, "config", "Invalid reference namespace");
        }
        c.forEach(child -> references(child, available, f, id, errors));
    }

    private void add(List<Issue> errors, Flow f, String id, String field, String message) {
        errors.add(new Issue("FLOW_INVALID", f.id(), id, field, message));
    }

    public Plan plan(Flow f) {
        if (!validate(f).isEmpty()) throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "Flow validation failed"
        );
        Map<String, Flow.Node> nodes = new LinkedHashMap<>();
        f.nodes().forEach(n -> nodes.put(n.id(), n));
        Map<String, Map<String, String>> edges = new HashMap<>();
        f.edges().forEach(e ->
            edges.computeIfAbsent(e.from(), k -> new HashMap<>()).put(e.port(), e.to())
        );
        return new Plan(f, nodes, edges);
    }
}
