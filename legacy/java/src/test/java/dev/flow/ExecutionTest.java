package dev.flow;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.core.*;
import dev.flow.db.Databases;
import java.net.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class ExecutionTest {

    @Test
    void numericWireFormatPreservesDecimalAndLargeInteger() throws Exception {
        var eval = new Expressions(json.createObjectNode());
        JsonNode sum = eval.evaluate(
            json.readTree(
                "{\"op\":\"add\",\"args\":[{\"type\":\"decimal\",\"value\":\"0.1\"},{\"type\":\"decimal\",\"value\":\"0.2\"}]}"
            )
        );
        assertEquals("decimal", sum.path("type").asText());
        assertEquals("0.3", sum.path("value").asText());
        JsonNode large = eval.evaluate(
            json.readTree("{\"op\":\"toNumber\",\"args\":[\"9007199254740993\"]}")
        );
        assertEquals("integer", large.path("type").asText());
        assertEquals("9007199254740993", large.path("value").asText());
        assertThrows(FlowFault.class, () ->
            eval.evaluate(json.readTree("{\"op\":\"toNumber\",\"args\":[\"1e999999999\"]}"))
        );
    }

    @Test
    void queryExampleHasPathParameterOpenApiAndNoGetRequestBody() throws Exception {
        Flow flow = json.readValue(
            java.nio.file.Files.readString(java.nio.file.Path.of("examples/user-query-flow.json")),
            Flow.class
        );
        assertTrue(new Validator().validate(flow).isEmpty());
        JsonNode api = new dev.flow.platform.Generator(json, new Validator()).openapi(flow);
        JsonNode operation = api.path("paths").path("/users/{userId}").path("get");
        assertEquals("userId", operation.path("parameters").get(0).path("name").asText());
        assertEquals(
            "integer",
            operation.path("parameters").get(0).path("schema").path("type").asText()
        );
        assertFalse(operation.has("requestBody"));
        assertTrue(operation.path("responses").has("404"));
    }

    final ObjectMapper json = new ObjectMapper();

    Flow.Node node(String id, String type, String config) throws Exception {
        return new Flow.Node(id, type, id, json.readTree(config));
    }

    Flow flow(List<Flow.Node> nodes, List<Flow.Edge> edges) throws Exception {
        return new Flow(
            "1.0",
            "test",
            1,
            "test",
            json.readTree("{\"type\":\"object\"}"),
            json.readTree("{\"type\":\"object\"}"),
            json.readTree("{\"databases\":[\"main\"]}"),
            nodes,
            edges,
            json.readTree("{\"timeoutMs\":10000,\"authentication\":\"bearer\"}"),
            null
        );
    }

    Flow.Edge edge(String from, String port, String to) {
        return new Flow.Edge(from, port, to);
    }

    @Test
    void branchSelectsOnlyOnePathAndBusinessErrorKeepsItsCode() throws Exception {
        Flow f = flow(
            List.of(
                node("start", "trigger.http", "{\"method\":\"POST\",\"path\":\"/branch\"}"),
                node("branch", "branch", "{\"condition\":false}"),
                node("yes", "response.http", "{\"status\":200,\"body\":{}}"),
                node(
                    "no",
                    "error.raise",
                    "{\"code\":\"NOT_FOUND\",\"status\":404,\"message\":\"Missing\"}"
                )
            ),
            List.of(
                edge("start", "success", "branch"),
                edge("branch", "true", "yes"),
                edge("branch", "false", "no")
            )
        );
        try (Databases db = new Databases(json, json.createObjectNode())) {
            var result = new Engine(json, db).run(
                new Validator().plan(f),
                json.createObjectNode(),
                true
            );
            assertEquals(404, result.status());
            assertEquals("NOT_FOUND", result.body().path("code").asText());
            assertEquals("BUSINESS_ERROR", result.body().path("category").asText());
            assertFalse(
                result
                    .trace()
                    .stream()
                    .anyMatch(t -> t.nodeId().equals("yes"))
            );
        }
    }

    @Test
    void previewCommitRollsBackButProductionCommitPersists() throws Exception {
        String url = "jdbc:h2:mem:" + UUID.randomUUID() + ";DB_CLOSE_DELAY=-1";
        try (Connection setup = DriverManager.getConnection(url)) {
            setup.createStatement().execute("CREATE TABLE items(id INT)");
        }
        Flow f = flow(
            List.of(
                node("start", "trigger.http", "{\"method\":\"POST\",\"path\":\"/tx\"}"),
                node("begin", "transaction.begin", "{\"databaseRef\":\"main\"}"),
                node(
                    "insert",
                    "db.command",
                    "{\"databaseRef\":\"main\",\"sql\":\"INSERT INTO items(id) VALUES(:id)\",\"parameters\":{\"id\":1}}"
                ),
                node("commit", "transaction.commit", "{}"),
                node("response", "response.http", "{\"status\":200,\"body\":{}}")
            ),
            List.of(
                edge("start", "success", "begin"),
                edge("begin", "success", "insert"),
                edge("insert", "success", "commit"),
                edge("commit", "success", "response")
            )
        );
        Databases db = mock(Databases.class);
        when(db.previewCommandAllowed("main")).thenReturn(true);
        try (Databases real = new Databases(json, json.createObjectNode())) {
            when(db.connect("main")).thenAnswer(inv -> DriverManager.getConnection(url));
            when(
                db.execute(
                    any(),
                    anyString(),
                    any(),
                    anyBoolean(),
                    anyInt(),
                    anyInt(),
                    anyInt(),
                    anyString()
                )
            ).thenAnswer(inv ->
                real.execute(
                    inv.getArgument(0),
                    inv.getArgument(1),
                    inv.getArgument(2),
                    inv.getArgument(3),
                    inv.getArgument(4),
                    inv.getArgument(5),
                    inv.getArgument(6),
                    inv.getArgument(7)
                )
            );
            assertEquals(
                200,
                new Engine(json, db)
                    .run(new Validator().plan(f), json.createObjectNode(), true)
                    .status()
            );
            try (
                Connection c = DriverManager.getConnection(url);
                ResultSet r = c.createStatement().executeQuery("SELECT COUNT(*) FROM items")
            ) {
                r.next();
                assertEquals(0, r.getInt(1));
            }
            assertEquals(
                200,
                new Engine(json, db)
                    .run(new Validator().plan(f), json.createObjectNode(), false)
                    .status()
            );
            try (
                Connection c = DriverManager.getConnection(url);
                ResultSet r = c.createStatement().executeQuery("SELECT COUNT(*) FROM items")
            ) {
                r.next();
                assertEquals(1, r.getInt(1));
            }
        }
    }

    @Test
    void typeErrorsAndMissingSqlParametersAreRejectedBeforeExecution() throws Exception {
        Flow f = flow(
            List.of(
                node("start", "trigger.http", "{\"method\":\"GET\",\"path\":\"/types\"}"),
                node("branch", "branch", "{\"condition\":\"true\"}"),
                node("response", "response.http", "{\"status\":200,\"body\":{}}")
            ),
            List.of(
                edge("start", "success", "branch"),
                edge("branch", "true", "response"),
                edge("branch", "false", "response")
            )
        );
        assertTrue(
            new Validator()
                .validate(f)
                .stream()
                .anyMatch(i -> i.message().contains("boolean"))
        );
        f = flow(
            List.of(
                node("start", "trigger.http", "{\"method\":\"GET\",\"path\":\"/sql\"}"),
                node(
                    "query",
                    "db.query",
                    "{\"databaseRef\":\"main\",\"sql\":\"SELECT id FROM items WHERE id=:id\",\"parameters\":{}}"
                ),
                node("response", "response.http", "{\"status\":200,\"body\":{}}")
            ),
            List.of(edge("start", "success", "query"), edge("query", "success", "response"))
        );
        assertTrue(
            new Validator()
                .validate(f)
                .stream()
                .anyMatch(i -> i.message().contains("Missing SQL"))
        );
    }

    @Test
    void httpAdapterUsesTrustedServiceAndNeverFollowsRedirects() throws Exception {
        var server = com.sun.net.httpserver.HttpServer.create(
            new InetSocketAddress("127.0.0.1", 0),
            0
        );
        AtomicInteger redirected = new AtomicInteger();
        server.createContext("/ok", exchange -> {
            byte[] body = "{\"value\":1}".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.createContext("/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "/target");
            exchange.sendResponseHeaders(302, -1);
            exchange.close();
        });
        server.createContext("/target", exchange -> {
            redirected.incrementAndGet();
            exchange.sendResponseHeaders(200, -1);
            exchange.close();
        });
        server.start();
        try {
            ObjectNode config = json.createObjectNode();
            config
                .putObject("main")
                .put("baseUrl", "http://127.0.0.1:" + server.getAddress().getPort())
                .put("allowHttpForDevelopment", true);
            HttpServices services = new HttpServices(json, config);
            Expressions eval = new Expressions(json.createObjectNode());
            long deadline = System.nanoTime() + 5_000_000_000L;
            assertEquals(
                1,
                services
                    .call(
                        json.readTree("{\"serviceRef\":\"main\",\"path\":\"ok\"}"),
                        eval,
                        deadline
                    )
                    .path("body")
                    .path("value")
                    .asInt()
            );
            assertThrows(FlowFault.class, () ->
                services.call(
                    json.readTree("{\"serviceRef\":\"main\",\"path\":\"redirect\"}"),
                    eval,
                    deadline
                )
            );
            assertEquals(0, redirected.get());
            assertThrows(FlowFault.class, () ->
                services.call(
                    json.readTree(
                        "{\"serviceRef\":\"main\",\"path\":\"https://untrusted.example\"}"
                    ),
                    eval,
                    deadline
                )
            );
        } finally {
            server.stop(0);
        }
    }
}
