package dev.flow;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.core.*;
import dev.flow.db.*;
import dev.flow.platform.Generator;
import java.io.*;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import java.util.zip.*;
import org.junit.jupiter.api.Test;

class CoreTest {

    final ObjectMapper json = new ObjectMapper();

    Flow sample() throws Exception {
        return json.readValue(Files.readString(Path.of("examples/hello-flow.json")), Flow.class);
    }

    ObjectNode sampleTree() throws Exception {
        return (ObjectNode) json.valueToTree(sample());
    }

    @Test
    void previewExecutesSharedRuntimeAndMasksTrace() throws Exception {
        Flow f = sample();
        try (Databases db = new Databases(json, json.createObjectNode())) {
            var result = new Engine(json, db).run(
                new Validator().plan(f),
                json.readTree("{\"name\":\"테스트\"}"),
                true
            );
            assertEquals(200, result.status());
            assertEquals("안녕하세요, 테스트님!", result.body().path("message").asText());
            assertEquals(3, result.trace().size());
            assertFalse(json.writeValueAsString(result.trace()).contains("테스트"));
        }
    }

    @Test
    void cycleAndPathDependentOutputAreRejected() throws Exception {
        ObjectNode tree = sampleTree();
        ((ArrayNode) tree.get("edges"))
            .addObject()
            .put("from", "greeting")
            .put("port", "error")
            .put("to", "start");
        assertTrue(
            new Validator()
                .validate(json.treeToValue(tree, Flow.class))
                .stream()
                .anyMatch(i -> i.message().contains("Cycle"))
        );
        tree = sampleTree();
        ((ObjectNode) tree.get("nodes").get(1).get("config")).set(
            "mapping",
            json.readTree("{\"ref\":\"nodes.response.output.foo\"}")
        );
        assertTrue(
            new Validator()
                .validate(json.treeToValue(tree, Flow.class))
                .stream()
                .anyMatch(i -> i.message().contains("not guaranteed"))
        );
    }

    @Test
    void schemaAndStrictExpressionsRejectInvalidInputs() throws Exception {
        assertThrows(FlowFault.class, () ->
            Contracts.check(sample().inputSchema(), json.readTree("{\"name\":1}"))
        );
        Expressions e = new Expressions(json.createObjectNode());
        assertThrows(FlowFault.class, () ->
            e.evaluate(json.readTree("{\"op\":\"add\",\"args\":[\"1\",2]}"))
        );
        assertThrows(FlowFault.class, () ->
            e.evaluate(json.readTree("{\"ref\":\"input.missing\"}"))
        );
        assertTrue(e.evaluate(json.readTree("{\"op\":\"isNull\",\"args\":[null]}")).booleanValue());
        assertThrows(FlowFault.class, () ->
            Contracts.rejectRemote(json.readTree("{\"$ref\":\"https://example.com/schema\"}"))
        );
    }

    @Test
    void sqlPolicyRejectsMultipleAndDdlStatements() {
        assertThrows(FlowFault.class, () -> SqlPolicy.check("SELECT 1; DELETE FROM users", false));
        assertThrows(FlowFault.class, () -> SqlPolicy.check("CREATE TABLE users(id int)", true));
        assertDoesNotThrow(() -> SqlPolicy.check("SELECT id FROM users WHERE id=:id", false));
    }

    @Test
    void jdbcBindsValuesLimitsRowsAndRollsBack() throws Exception {
        try (Connection c = DriverManager.getConnection("jdbc:h2:mem:flowtest")) {
            c.createStatement().execute("CREATE TABLE users(id INT, name VARCHAR(80))");
            c.createStatement().execute("INSERT INTO users VALUES(1,'a'),(2,'b'),(3,'c')");
            try (Databases db = new Databases(json, json.createObjectNode())) {
                JsonNode result = db.execute(
                    c,
                    "SELECT * FROM users ORDER BY id",
                    json.createObjectNode(),
                    false,
                    2,
                    10000,
                    5
                );
                assertEquals(2, result.path("rows").size());
                assertTrue(result.path("truncated").asBoolean());
                result = db.execute(
                    c,
                    "SELECT * FROM users WHERE name=:name",
                    json.readTree("{\"name\":\"' OR 1=1 --\"}"),
                    false,
                    100,
                    10000,
                    5
                );
                assertEquals(0, result.path("rows").size());
                JsonNode bounded = db.execute(
                    c,
                    "SELECT * FROM users ORDER BY id",
                    json.createObjectNode(),
                    false,
                    100,
                    650,
                    5
                );
                assertTrue(json.writeValueAsBytes(bounded).length <= 650);
                assertTrue(bounded.path("truncated").asBoolean());
                c.setAutoCommit(false);
                db.execute(
                    c,
                    "UPDATE users SET name=:name WHERE id=:id",
                    json.readTree("{\"name\":\"changed\",\"id\":1}"),
                    true,
                    100,
                    10000,
                    5
                );
                c.rollback();
                assertEquals(
                    "a",
                    db
                        .execute(
                            c,
                            "SELECT name FROM users WHERE id=1",
                            json.createObjectNode(),
                            false,
                            100,
                            10000,
                            5
                        )
                        .path("row")
                        .path("NAME")
                        .asText()
                );
                assertThrows(FlowFault.class, () ->
                    db.execute(
                        c,
                        "SELECT * FROM users WHERE id=:missing",
                        json.createObjectNode(),
                        false,
                        100,
                        10000,
                        5
                    )
                );
            }
        }
    }

    @Test
    void generationIsReproducibleAndExcludesManagementCode() throws Exception {
        Generator g = new Generator(json, new Validator());
        byte[] one = g.generate(sample()),
            two = g.generate(sample());
        assertArrayEquals(one, two);
        Set<String> files = new HashSet<>();
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(one))) {
            ZipEntry e;
            while ((e = zip.getNextEntry()) != null) files.add(e.getName());
        }
        assertTrue(files.contains("src/main/java/dev/flow/core/Engine.java"));
        assertTrue(files.contains("flows/hello.json"));
        assertTrue(files.contains("openapi.json"));
        assertFalse(files.stream().anyMatch(n -> n.contains("platform/")));
        ObjectNode tree = sampleTree();
        tree.set("ui", json.createObjectNode().put("changed", true));
        assertArrayEquals(one, g.generate(json.treeToValue(tree, Flow.class)));
    }

    @Test
    void transactionWithoutCommitCannotReturnResponse() throws Exception {
        ObjectNode tree = sampleTree();
        tree.with("resources").putArray("databases").add("main");
        ObjectNode node = (ObjectNode) tree.get("nodes").get(1);
        node.put("type", "transaction.begin");
        node.set("config", json.createObjectNode().put("databaseRef", "main"));
        ((ObjectNode) tree.get("nodes").get(2).get("config")).set(
            "body",
            json.createObjectNode().put("message", "ok")
        );
        assertTrue(
            new Validator()
                .validate(json.treeToValue(tree, Flow.class))
                .stream()
                .anyMatch(i -> i.message().contains("active transaction"))
        );
    }
}
