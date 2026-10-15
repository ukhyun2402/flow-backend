package dev.flow.runtime;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import dev.flow.core.*;
import jakarta.servlet.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.beans.factory.SmartInitializingSingleton;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.*;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.servlet.mvc.method.RequestMappingInfo;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;

@Controller
@ConditionalOnProperty(name = "flow.mode", havingValue = "runtime")
public class RuntimeRoutes implements SmartInitializingSingleton {

    private final ObjectMapper json;
    private final Validator validator;
    private final Engine engine;
    private final RequestMappingHandlerMapping mappings;
    private final Map<String, Flow> flows = new HashMap<>();

    public RuntimeRoutes(
        ObjectMapper json,
        Validator validator,
        Engine engine,
        RequestMappingHandlerMapping mappings
    ) {
        this.json = json;
        this.validator = validator;
        this.engine = engine;
        this.mappings = mappings;
    }

    public void afterSingletonsInstantiated() {
        try (
            var files = Files.list(Path.of(System.getenv().getOrDefault("FLOW_DIRECTORY", "flows")))
        ) {
            for (Path file : files
                .filter(p -> p.toString().endsWith(".json"))
                .sorted()
                .toList()) {
                Flow f = json.readValue(Files.readString(file), Flow.class);
                validator.plan(f);
                String auth = f.settings().path("authentication").asText();
                if (!Set.of("public", "bearer").contains(auth)) throw new IllegalStateException(
                    "Explicit authentication policy required"
                );
                if (
                    auth.equals("bearer") &&
                    (System.getenv("FLOW_RUNTIME_TOKEN") == null ||
                        System.getenv("FLOW_RUNTIME_TOKEN").length() < 24)
                ) throw new IllegalStateException(
                    "FLOW_RUNTIME_TOKEN must contain at least 24 characters"
                );
                Flow.Node trigger = f
                    .nodes()
                    .stream()
                    .filter(n -> n.type().equals("trigger.http"))
                    .findFirst()
                    .orElseThrow();
                String path = trigger.config().path("path").asText();
                String method = trigger.config().path("method").asText();
                String key = method + " " + path;
                if (flows.putIfAbsent(key, f) != null) throw new IllegalStateException(
                    "API route conflict"
                );
                RequestMappingInfo mapping = RequestMappingInfo.paths(path)
                    .methods(RequestMethod.valueOf(method))
                    .options(mappings.getBuilderConfiguration())
                    .build();
                mappings.registerMapping(
                    mapping,
                    this,
                    RuntimeRoutes.class.getMethod("execute", HttpServletRequest.class)
                );
            }
        } catch (Exception ex) {
            throw new IllegalStateException("Unable to register generated flows", ex);
        }
    }

    @ResponseBody
    public ResponseEntity<?> execute(HttpServletRequest request) throws Exception {
        String pattern = request
            .getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE)
            .toString();
        Flow f = flows.get(request.getMethod() + " " + pattern);
        if (f.settings().path("authentication").asText().equals("bearer")) {
            String expected = "Bearer " + System.getenv("FLOW_RUNTIME_TOKEN");
            String supplied = Optional.ofNullable(request.getHeader("Authorization")).orElse("");
            if (
                !MessageDigest.isEqual(
                    expected.getBytes(StandardCharsets.UTF_8),
                    supplied.getBytes(StandardCharsets.UTF_8)
                )
            ) throw new FlowFault("UNAUTHORIZED", 401, "Bearer authentication required");
        }
        byte[] bytes = request.getInputStream().readNBytes(1_048_577);
        if (bytes.length > 1_048_576) throw new FlowFault(
            "VALIDATION_ERROR",
            413,
            "Request body too large"
        );
        JsonNode body = bytes.length == 0 ? json.createObjectNode() : json.readTree(bytes);
        ObjectNode sources = json.createObjectNode();
        sources.set("body", body);
        sources.set(
            "path",
            json.valueToTree(request.getAttribute(HandlerMapping.URI_TEMPLATE_VARIABLES_ATTRIBUTE))
        );
        ObjectNode query = sources.putObject("query");
        ObjectNode headers = sources.putObject("headers");
        var headerNames = request.getHeaderNames();
        while (headerNames.hasMoreElements()) {
            String name = headerNames.nextElement();
            headers.put(name.toLowerCase(Locale.ROOT), request.getHeader(name));
        }
        request.getParameterMap().forEach((k, v) -> query.put(k, v[0]));
        ObjectNode input = json.createObjectNode();
        Flow.Node trigger = f
            .nodes()
            .stream()
            .filter(n -> n.type().equals("trigger.http"))
            .findFirst()
            .orElseThrow();
        var fields = trigger.config().path("input").fields();
        while (fields.hasNext()) {
            var field = fields.next();
            JsonNode value = sources;
            for (String part : field.getValue().path("source").asText().split("\\."))
                value = value.path(part);
            if (value.isMissingNode()) continue;
            if (field.getValue().has("convert")) {
                String text = value.asText();
                value = switch (field.getValue().path("convert").asText()) {
                    case "integer" -> BigIntegerNode.valueOf(new java.math.BigInteger(text));
                    case "number" -> DecimalNode.valueOf(new java.math.BigDecimal(text));
                    case "string" -> TextNode.valueOf(text);
                    case "boolean" -> {
                        if (
                            !Set.of("true", "false").contains(text)
                        ) throw new IllegalArgumentException();
                        yield BooleanNode.valueOf(Boolean.parseBoolean(text));
                    }
                    default -> throw new IllegalArgumentException();
                };
            }
            input.set(field.getKey(), value);
        }
        Engine.Result result = engine.run(validator.plan(f), input, false);
        var logger = org.slf4j.LoggerFactory.getLogger("flow.trace");
        for (Engine.Trace t : result.trace()) logger.info("{}", json.writeValueAsString(t));
        var response = ResponseEntity.status(result.status());
        result.headers().forEach(response::header);
        return response.body(result.body());
    }
}
