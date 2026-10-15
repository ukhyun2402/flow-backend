package dev.flow.platform;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Set;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@ConditionalOnProperty(name = "flow.mode", havingValue = "platform", matchIfMissing = true)
public class Access extends OncePerRequestFilter {

    protected void doFilterInternal(
        HttpServletRequest request,
        HttpServletResponse response,
        FilterChain chain
    ) throws ServletException, IOException {
        if (!request.getRequestURI().startsWith("/api/")) {
            chain.doFilter(request, response);
            return;
        }
        String header = request.getHeader("Authorization");
        String role = matches(header, "FLOW_ADMIN_TOKEN")
            ? "admin"
            : matches(header, "FLOW_EDITOR_TOKEN")
              ? "editor"
              : matches(header, "FLOW_RUNNER_TOKEN")
                ? "runner"
                : null;
        if (role == null) {
            response.setStatus(401);
            response.setContentType("application/json");
            response
                .getWriter()
                .write(
                    "{\"code\":\"UNAUTHORIZED\",\"message\":\"Configure and supply a platform bearer token\"}"
                );
            return;
        }
        request.setAttribute("flow.role", role);
        if (request.getContentLengthLong() > 5_000_000) {
            response.sendError(413);
            return;
        }
        if (Set.of("POST", "PUT", "PATCH").contains(request.getMethod())) {
            byte[] bytes = request.getInputStream().readNBytes(5_000_001);
            if (bytes.length > 5_000_000) {
                response.sendError(413);
                return;
            }
            var input = new java.io.ByteArrayInputStream(bytes);
            HttpServletRequestWrapper wrapped = new HttpServletRequestWrapper(request) {
                public ServletInputStream getInputStream() {
                    return new ServletInputStream() {
                        public int read() {
                            return input.read();
                        }

                        public boolean isFinished() {
                            return input.available() == 0;
                        }

                        public boolean isReady() {
                            return true;
                        }

                        public void setReadListener(ReadListener listener) {
                            throw new UnsupportedOperationException("Synchronous API");
                        }
                    };
                }
            };
            chain.doFilter(wrapped, response);
            return;
        }
        chain.doFilter(request, response);
    }

    private boolean matches(String actual, String env) {
        String token = System.getenv(env);
        return (
            token != null &&
            token.length() >= 24 &&
            actual != null &&
            MessageDigest.isEqual(
                ("Bearer " + token).getBytes(StandardCharsets.UTF_8),
                actual.getBytes(StandardCharsets.UTF_8)
            )
        );
    }

    public static void require(HttpServletRequest r, String... roles) {
        if (
            !java.util.Arrays.asList(roles).contains(r.getAttribute("flow.role"))
        ) throw new dev.flow.core.FlowFault("FORBIDDEN", 403, "Insufficient permission");
    }
}
