package dev.flow.core;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.db.Databases;
import java.sql.Connection;
import java.time.*;
import java.util.*;

public final class Engine {

    public record Trace(
        String executionId,
        String flowId,
        int flowRevision,
        String nodeId,
        String status,
        String startedAt,
        long durationMs,
        String errorCode
    ) {}

    public record Result(
        int status,
        JsonNode body,
        Map<String, String> headers,
        List<Trace> trace
    ) {}

    private final ObjectMapper json;
    private final Databases databases;
    private final HttpServices services;

    public Engine(ObjectMapper json, Databases databases) {
        this(json, databases, new HttpServices(json, json.createObjectNode()));
    }

    public Engine(ObjectMapper json, Databases databases, HttpServices services) {
        this.json = json;
        this.databases = databases;
        this.services = services;
    }

    public Result run(Validator.Plan plan, JsonNode input, boolean preview) {
        return run(plan, input, preview, UUID.randomUUID().toString());
    }

    public Result run(Validator.Plan plan, JsonNode input, boolean preview, String executionId) {
        try {
            UUID.fromString(executionId);
        } catch (Exception ex) {
            throw new FlowFault("VALIDATION_ERROR", 400, "Execution ID must be a UUID");
        }
        Flow f = plan.flow();
        Contracts.check(f.inputSchema(), input);
        List<Trace> traces = new ArrayList<>();
        ObjectNode root = json.createObjectNode();
        root.set("input", input);
        ObjectNode outputs = root.putObject("nodes");
        root.putObject("context")
            .put("requestId", executionId)
            .put("startedAt", Instant.now().toString());
        Expressions eval = new Expressions(root);
        String current = f
            .nodes()
            .stream()
            .filter(n -> n.type().equals("trigger.http"))
            .findFirst()
            .orElseThrow()
            .id();
        long deadline =
            System.nanoTime() +
            Math.min(60000, Math.max(1, f.settings().path("timeoutMs").asInt(10000))) * 1_000_000L;
        Connection tx = null;
        String txDb = null;
        try {
            while (current != null) {
                Flow.Node n = plan.nodes().get(current);
                JsonNode c = n.config();
                long start = System.nanoTime();
                String at = Instant.now().toString();
                String port = "success";
                JsonNode output = json.createObjectNode();
                try {
                    if (Thread.currentThread().isInterrupted()) throw new FlowFault(
                        "CANCELLED",
                        499,
                        "Execution cancelled"
                    );
                    if (System.nanoTime() >= deadline) throw new FlowFault(
                        "TIMEOUT",
                        504,
                        "Execution timed out"
                    );
                    switch (n.type()) {
                        case "trigger.http" -> output = input;
                        case "validate" -> {
                            JsonNode value = c.has("value") ? eval.evaluate(c.get("value")) : input;
                            Contracts.check(c.get("schema"), value);
                            output = value;
                        }
                        case "transform" -> output = eval.evaluate(c.get("mapping"));
                        case "branch" -> port = Expressions.bool(eval.evaluate(c.get("condition")))
                            ? "true"
                            : "false";
                        case "transaction.begin" -> {
                            txDb = c.path("databaseRef").asText();
                            if (
                                preview && !databases.previewCommandAllowed(txDb)
                            ) throw new FlowFault(
                                "VALIDATION_ERROR",
                                403,
                                "Transaction preview requires a verified test database"
                            );
                            tx = databases.connect(txDb);
                            if (c.has("isolation")) {
                                int isolation = switch (c.path("isolation").asText()) {
                                    case "READ_COMMITTED" -> Connection.TRANSACTION_READ_COMMITTED;
                                    case "REPEATABLE_READ" -> Connection.TRANSACTION_REPEATABLE_READ;
                                    case "SERIALIZABLE" -> Connection.TRANSACTION_SERIALIZABLE;
                                    default -> throw new FlowFault(
                                        "VALIDATION_ERROR",
                                        400,
                                        "Unsupported isolation level"
                                    );
                                };
                                if (
                                    !tx.getMetaData().supportsTransactionIsolationLevel(isolation)
                                ) throw new FlowFault(
                                    "VALIDATION_ERROR",
                                    400,
                                    "Database does not support requested isolation"
                                );
                                tx.setTransactionIsolation(isolation);
                            }
                            tx.setAutoCommit(false);
                        }
                        case "transaction.commit" -> {
                            if (preview) tx.rollback();
                            else tx.commit();
                            tx.close();
                            tx = null;
                            txDb = null;
                        }
                        case "transaction.rollback" -> {
                            tx.rollback();
                            tx.close();
                            tx = null;
                            txDb = null;
                        }
                        case "db.query", "db.command" -> {
                            String db = c.path("databaseRef").asText();
                            boolean command = n.type().equals("db.command");
                            if (
                                preview && command && !databases.previewCommandAllowed(db)
                            ) throw new FlowFault(
                                "VALIDATION_ERROR",
                                403,
                                "Write preview requires a verified test database"
                            );
                            JsonNode parameters = eval.evaluate(c.path("parameters"));
                            if (parameters.isMissingNode()) parameters = json.createObjectNode();
                            int seconds = Math.max(
                                1,
                                (int) ((deadline - System.nanoTime()) / 1_000_000_000L)
                            );
                            if (tx != null) output = databases.execute(
                                tx,
                                c.path("sql").asText(),
                                parameters,
                                command,
                                100,
                                5_000_000,
                                seconds,
                                executionId
                            );
                            else try (Connection con = databases.connect(db)) {
                                if (preview && command) con.setAutoCommit(false);
                                try {
                                    output = databases.execute(
                                        con,
                                        c.path("sql").asText(),
                                        parameters,
                                        command,
                                        100,
                                        5_000_000,
                                        seconds,
                                        executionId
                                    );
                                } finally {
                                    if (preview && command) con.rollback();
                                }
                            }
                            if (
                                !command &&
                                c.path("resultMode").asText().equals("zeroOrOne") &&
                                (output.path("rows").size() > 1 ||
                                    output.path("truncated").asBoolean())
                            ) throw new FlowFault("DB_ERROR", 422, "Expected at most one row");
                        }
                        case "http.call" -> output = services.call(c, eval, deadline);
                        case "error.raise" -> throw new FlowFault(
                            c.path("code").asText("BUSINESS_ERROR"),
                            boundedStatus(c.path("status").asInt(400)),
                            c.path("message").asText("Business error"),
                            "BUSINESS_ERROR"
                        );
                        case "response.http" -> {
                            JsonNode body = eval.evaluate(c.get("body"));
                            Contracts.check(f.outputSchema(), body);
                            Map<String, String> headers = new HashMap<>();
                            JsonNode configured = eval.evaluate(c.path("headers"));
                            configured.fields().forEachRemaining(e -> {
                                String key = e.getKey().toLowerCase(Locale.ROOT);
                                String value = e.getValue().asText();
                                if (
                                    !Set.of(
                                        "x-request-id",
                                        "cache-control",
                                        "location",
                                        "content-language"
                                    ).contains(key) ||
                                    value.contains("\r") ||
                                    value.contains("\n")
                                ) throw new FlowFault(
                                    "VALIDATION_ERROR",
                                    400,
                                    "Unsupported response header"
                                );
                                headers.put(e.getKey(), value);
                            });
                            traces.add(trace(executionId, f, n, "SUCCESS", at, start, null));
                            return new Result(
                                boundedStatus(c.path("status").asInt(200)),
                                body,
                                Map.copyOf(headers),
                                List.copyOf(traces)
                            );
                        }
                        default -> throw new FlowFault("INTERNAL_ERROR", 500, "Unsupported node");
                    }
                    if (c.has("outputSchema")) Contracts.check(c.get("outputSchema"), output);
                    outputs.putObject(n.id()).set("output", output);
                    traces.add(trace(executionId, f, n, "SUCCESS", at, start, null));
                } catch (Exception ex) {
                    FlowFault fault =
                        ex instanceof FlowFault ff
                            ? ff
                            : ex instanceof java.sql.SQLTimeoutException
                              ? new FlowFault("TIMEOUT", 504, "SQL timed out")
                              : new FlowFault("DB_ERROR", 500, "Database operation failed");
                    traces.add(trace(executionId, f, n, "ERROR", at, start, fault.code()));
                    port = "error";
                    if (
                        !plan.next().getOrDefault(current, Map.of()).containsKey(port)
                    ) return new Result(
                        fault.status(),
                        json
                            .createObjectNode()
                            .put("code", fault.code())
                            .put("category", fault.category())
                            .put("message", fault.getMessage())
                            .put("executionId", executionId),
                        Map.of(),
                        List.copyOf(traces)
                    );
                }
                current = plan.next().getOrDefault(current, Map.of()).get(port);
            }
            throw new FlowFault("INTERNAL_ERROR", 500, "No response produced");
        } finally {
            if (tx != null) {
                try {
                    tx.rollback();
                } catch (Exception ignored) {}
                try {
                    tx.close();
                } catch (Exception ignored) {}
            }
        }
    }

    private int boundedStatus(int s) {
        if (s < 200 || s > 599) throw new FlowFault("VALIDATION_ERROR", 400, "Invalid HTTP status");
        return s;
    }

    private Trace trace(
        String id,
        Flow f,
        Flow.Node n,
        String status,
        String at,
        long start,
        String error
    ) {
        return new Trace(
            id,
            f.id(),
            f.revision(),
            n.id(),
            status,
            at,
            (System.nanoTime() - start) / 1_000_000,
            error
        );
    }
}
