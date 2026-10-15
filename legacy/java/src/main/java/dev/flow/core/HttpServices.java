package dev.flow.core;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;

/** Trusted service origins are configured outside Flow; redirects are never followed. */
public final class HttpServices {

    private final ObjectMapper json;
    private final JsonNode config;
    private final HttpClient client = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5))
        .followRedirects(HttpClient.Redirect.NEVER)
        .build();

    public HttpServices(ObjectMapper json, JsonNode config) {
        this.json = json;
        this.config = config;
    }

    public JsonNode call(JsonNode node, Expressions eval, long deadline) {
        JsonNode service = config.path(node.path("serviceRef").asText());
        if (!service.isObject()) throw new FlowFault(
            "EXTERNAL_API_ERROR",
            503,
            "External service is not configured"
        );
        try {
            URI base = URI.create(service.path("baseUrl").asText());
            if (
                !"https".equals(base.getScheme()) &&
                !(
                    "http".equals(base.getScheme()) &&
                    service.path("allowHttpForDevelopment").asBoolean()
                )
            ) throw new FlowFault("EXTERNAL_API_ERROR", 400, "HTTPS service origin required");
            String path = node.path("path").asText("");
            if (
                path.contains("..") ||
                path.contains(":") ||
                path.contains("\\") ||
                path.startsWith("//") ||
                path.contains("#") ||
                path.contains("?")
            ) throw new FlowFault("VALIDATION_ERROR", 400, "Invalid service path");
            String prefix = base.toString().replaceAll("/+$", "");
            URI target = URI.create(prefix + "/" + path.replaceAll("^/+", ""));
            if (
                !Objects.equals(base.getHost(), target.getHost()) ||
                base.getPort() != target.getPort()
            ) throw new FlowFault("VALIDATION_ERROR", 400, "Service origin mismatch");
            String method = node.path("method").asText("GET");
            if (
                !Set.of("GET", "POST", "PUT", "PATCH", "DELETE").contains(method)
            ) throw new FlowFault("VALIDATION_ERROR", 400, "Invalid service method");
            long nanos = deadline - System.nanoTime();
            if (nanos <= 0) throw new FlowFault("TIMEOUT", 504, "Execution timed out");
            HttpRequest.Builder request = HttpRequest.newBuilder(target)
                .timeout(Duration.ofNanos(nanos))
                .header("Accept", "application/json");
            if (service.has("bearerSecretRef")) {
                String token = System.getenv(service.get("bearerSecretRef").asText());
                if (token == null) throw new FlowFault(
                    "EXTERNAL_API_ERROR",
                    503,
                    "Service secret unavailable"
                );
                request.header("Authorization", "Bearer " + token);
            }
            byte[] payload = node.has("body")
                ? json.writeValueAsBytes(eval.evaluate(node.get("body")))
                : new byte[0];
            if (payload.length > 1_048_576) throw new FlowFault(
                "VALIDATION_ERROR",
                413,
                "Service request too large"
            );
            request
                .header("Content-Type", "application/json")
                .method(
                    method,
                    payload.length == 0
                        ? HttpRequest.BodyPublishers.noBody()
                        : HttpRequest.BodyPublishers.ofByteArray(payload)
                );
            // BodyHandler reads only a bounded byte array and is covered by HttpRequest.timeout.
            var response = client.send(request.build(), info -> new LimitedSubscriber(1_048_576));
            if (response.statusCode() < 200 || response.statusCode() > 299) throw new FlowFault(
                "EXTERNAL_API_ERROR",
                502,
                "External service returned an error"
            );
            ObjectNode out = json.createObjectNode().put("status", response.statusCode());
            out.set(
                "body",
                response.body().length == 0 ? json.nullNode() : json.readTree(response.body())
            );
            return out;
        } catch (FlowFault ex) {
            throw ex;
        } catch (HttpTimeoutException ex) {
            throw new FlowFault("TIMEOUT", 504, "External service timed out");
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new FlowFault("CANCELLED", 499, "Execution cancelled");
        } catch (Exception ex) {
            throw new FlowFault("EXTERNAL_API_ERROR", 502, "External service call failed");
        }
    }

    private static final class LimitedSubscriber implements HttpResponse.BodySubscriber<byte[]> {

        private final java.util.concurrent.CompletableFuture<byte[]> result =
            new java.util.concurrent.CompletableFuture<>();
        private final java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        private final int max;
        private java.util.concurrent.Flow.Subscription subscription;

        LimitedSubscriber(int max) {
            this.max = max;
        }

        public java.util.concurrent.CompletionStage<byte[]> getBody() {
            return result;
        }

        public void onSubscribe(java.util.concurrent.Flow.Subscription s) {
            subscription = s;
            s.request(1);
        }

        public void onNext(List<java.nio.ByteBuffer> chunks) {
            for (var chunk : chunks) {
                if (bytes.size() + chunk.remaining() > max) {
                    subscription.cancel();
                    result.completeExceptionally(new IllegalStateException("Response too large"));
                    return;
                }
                byte[] b = new byte[chunk.remaining()];
                chunk.get(b);
                bytes.writeBytes(b);
            }
            subscription.request(1);
        }

        public void onError(Throwable t) {
            result.completeExceptionally(t);
        }

        public void onComplete() {
            result.complete(bytes.toByteArray());
        }
    }
}
