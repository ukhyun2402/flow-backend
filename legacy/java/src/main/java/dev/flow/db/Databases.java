package dev.flow.db;

import com.fasterxml.jackson.databind.*;
import com.fasterxml.jackson.databind.node.*;
import com.zaxxer.hikari.*;
import dev.flow.core.FlowFault;
import java.math.*;
import java.sql.*;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.jdbc.core.namedparam.*;
import org.springframework.jdbc.support.JdbcUtils;

public final class Databases implements AutoCloseable {

    private final ObjectMapper json;
    private final Map<String, HikariDataSource> pools = new ConcurrentHashMap<>();
    private final Map<String, Statement> active = new ConcurrentHashMap<>();
    private final Set<String> cancelled = ConcurrentHashMap.newKeySet();
    private final JsonNode config;

    public Databases(ObjectMapper json, JsonNode config) {
        this.json = json;
        this.config = config;
    }

    public synchronized Connection connect(String id) throws SQLException {
        JsonNode c = config.path(id);
        if (!c.isObject()) throw new FlowFault(
            "DB_ERROR",
            503,
            "Database resource is not configured"
        );
        HikariDataSource pool = pools.get(id);
        if (pool == null) {
            String vendor = c.path("vendor").asText();
            String driver = switch (vendor) {
                case "mysql" -> "com.mysql.cj.jdbc.Driver";
                case "oracle" -> "oracle.jdbc.OracleDriver";
                case "tibero" -> "com.tmax.tibero.jdbc.TbDriver";
                default -> throw new FlowFault("DB_ERROR", 400, "Unsupported database vendor");
            };
            String secret = System.getenv(c.path("passwordSecretRef").asText());
            if (secret == null) throw new FlowFault(
                "DB_ERROR",
                503,
                "Database secret is unavailable"
            );
            HikariConfig hc = new HikariConfig();
            hc.setDriverClassName(driver);
            hc.setJdbcUrl(c.path("jdbcUrl").asText());
            hc.setUsername(c.path("username").asText());
            hc.setPassword(secret);
            hc.setMaximumPoolSize(5);
            hc.setConnectionTimeout(5000);
            hc.setPoolName("flow-" + id);
            pool = new HikariDataSource(hc);
            pools.put(id, pool);
        }
        return pool.getConnection();
    }

    public boolean previewCommandAllowed(String id) {
        JsonNode c = config.path(id);
        return (
            Set.of("development", "test").contains(c.path("environment").asText()) &&
            c.path("rollbackSafetyVerified").asBoolean(false)
        );
    }

    public ObjectNode execute(
        Connection connection,
        String sql,
        JsonNode params,
        boolean command,
        int maxRows,
        int maxBytes,
        int timeoutSeconds
    ) throws SQLException {
        return execute(
            connection,
            sql,
            params,
            command,
            maxRows,
            maxBytes,
            timeoutSeconds,
            UUID.randomUUID().toString()
        );
    }

    public ObjectNode execute(
        Connection connection,
        String sql,
        JsonNode params,
        boolean command,
        int maxRows,
        int maxBytes,
        int timeoutSeconds,
        String executionId
    ) throws SQLException {
        SqlPolicy.check(sql, command);
        MapSqlParameterSource source = new MapSqlParameterSource();
        params.fields().forEachRemaining(e -> source.addValue(e.getKey(), parameter(e.getValue())));
        if (!command) sql = DatabaseDialect.fromProduct(
            connection.getMetaData().getDatabaseProductName()
        ).limit(sql, maxRows + 1);
        ParsedSql parsed = NamedParameterUtils.parseSqlStatement(sql);
        String positional = NamedParameterUtils.substituteNamedParameters(parsed, source);
        Object[] values;
        try {
            values = NamedParameterUtils.buildValueArray(parsed, source, null);
        } catch (RuntimeException ex) {
            throw new FlowFault("VALIDATION_ERROR", 400, "Missing SQL parameter");
        }
        long start = System.nanoTime();
        try (PreparedStatement ps = connection.prepareStatement(positional)) {
            if (active.putIfAbsent(executionId, ps) != null) throw new FlowFault(
                "EXECUTION_CONFLICT",
                409,
                "Execution ID is already active"
            );
            try {
                ps.setQueryTimeout(Math.max(1, timeoutSeconds));
                ps.setMaxRows(maxRows + 1);
                ps.setFetchSize(Math.min(maxRows + 1, 100));
                for (int i = 0; i < values.length; i++) ps.setObject(i + 1, values[i]);
                ObjectNode out = json.createObjectNode();
                if (command) {
                    out.put("affectedRows", ps.executeUpdate());
                } else try (ResultSet rs = ps.executeQuery()) {
                    ResultSetMetaData m = rs.getMetaData();
                    ArrayNode columns = out.putArray("columns"),
                        rows = out.putArray("rows");
                    for (int i = 1; i <= m.getColumnCount(); i++) columns
                        .addObject()
                        .put("name", m.getColumnLabel(i))
                        .put("type", m.getColumnTypeName(i))
                        .put("nullable", m.isNullable(i) != ResultSetMetaData.columnNoNulls);
                    int bytes;
                    try {
                        bytes = json.writeValueAsBytes(columns).length + 512;
                    } catch (Exception ex) {
                        throw new SQLException("Metadata conversion failed");
                    }
                    if (bytes > maxBytes) throw new FlowFault(
                        "DB_ERROR",
                        413,
                        "Column metadata exceeds response limit"
                    );
                    boolean truncated = false;
                    while (rs.next()) {
                        if (rows.size() >= maxRows) {
                            truncated = true;
                            break;
                        }
                        ObjectNode row = json.createObjectNode();
                        for (int i = 1; i <= m.getColumnCount(); i++) {
                            int type = m.getColumnType(i);
                            // Do not materialize unbounded LOBs into memory.
                            if (
                                Set.of(
                                    Types.BLOB,
                                    Types.CLOB,
                                    Types.NCLOB,
                                    Types.LONGVARBINARY,
                                    Types.LONGVARCHAR,
                                    Types.LONGNVARCHAR
                                ).contains(type)
                            ) throw new FlowFault("DB_ERROR", 422, "LOB preview is not supported");
                            Object value;
                            if (
                                Set.of(
                                    Types.VARCHAR,
                                    Types.NVARCHAR,
                                    Types.CHAR,
                                    Types.NCHAR
                                ).contains(type)
                            ) {
                                try (java.io.Reader reader = rs.getCharacterStream(i)) {
                                    if (reader == null) value = null;
                                    else {
                                        StringBuilder text = new StringBuilder();
                                        char[] buffer = new char[4096];
                                        int count;
                                        while (
                                            (count = reader.read(
                                                buffer,
                                                0,
                                                Math.min(
                                                    buffer.length,
                                                    maxBytes + 1 - text.length()
                                                )
                                            )) != -1
                                        ) {
                                            text.append(buffer, 0, count);
                                            if (text.length() > maxBytes) throw new FlowFault(
                                                "DB_ERROR",
                                                413,
                                                "A result field exceeds the byte limit"
                                            );
                                        }
                                        value = text.toString();
                                    }
                                } catch (java.io.IOException ex) {
                                    throw new SQLException("Result stream failed");
                                }
                            } else if (
                                Set.of(Types.BINARY, Types.VARBINARY).contains(type)
                            ) throw new FlowFault(
                                "DB_ERROR",
                                422,
                                "Binary preview is not supported"
                            );
                            else value = JdbcUtils.getResultSetValue(rs, i);
                            row.set(m.getColumnLabel(i), normalize(value));
                        }
                        int size;
                        try {
                            size = json.writeValueAsBytes(row).length;
                        } catch (Exception ex) {
                            throw new SQLException("Result conversion failed");
                        }
                        int cost = size * (rows.isEmpty() ? 2 : 1) + 1;
                        if (bytes + cost > maxBytes) {
                            truncated = true;
                            break;
                        }
                        bytes += cost;
                        rows.add(row);
                    }
                    out.put("truncated", truncated);
                    out.set("row", rows.isEmpty() ? NullNode.instance : rows.get(0));
                }
                out.put("executionId", executionId);
                out.put("durationMs", (System.nanoTime() - start) / 1_000_000);
                return out;
            } catch (SQLException ex) {
                if (cancelled.contains(executionId)) throw new FlowFault(
                    "CANCELLED",
                    499,
                    "SQL execution cancelled"
                );
                if (ex instanceof SQLTimeoutException) throw new FlowFault(
                    "TIMEOUT",
                    504,
                    "SQL execution timed out"
                );
                String state = ex.getSQLState();
                if (state != null && !state.matches("[A-Za-z0-9]{1,8}")) state = "unknown";
                throw new FlowFault(
                    "DB_ERROR",
                    500,
                    "Database operation failed (SQLState=" +
                        state +
                        ", vendorCode=" +
                        ex.getErrorCode() +
                        ")"
                );
            } finally {
                active.remove(executionId, ps);
                cancelled.remove(executionId);
            }
        }
    }

    public boolean cancel(String executionId) throws SQLException {
        Statement s = active.get(executionId);
        if (s == null) return false;
        cancelled.add(executionId);
        s.cancel();
        return true;
    }

    public JsonNode metadata(String id) throws SQLException {
        try (Connection c = connect(id)) {
            DatabaseMetaData m = c.getMetaData();
            ArrayNode tables = json.createArrayNode();
            try (
                ResultSet rs = m.getTables(c.getCatalog(), c.getSchema(), "%", new String[] {
                    "TABLE",
                    "VIEW",
                })
            ) {
                while (rs.next() && tables.size() < 200) {
                    String table = rs.getString("TABLE_NAME"),
                        schema = rs.getString("TABLE_SCHEM");
                    ObjectNode t = tables.addObject().put("name", table).put("schema", schema);
                    ArrayNode columns = t.putArray("columns");
                    try (ResultSet cols = m.getColumns(c.getCatalog(), schema, table, "%")) {
                        while (cols.next() && columns.size() < 500)
                            columns
                                .addObject()
                                .put("name", cols.getString("COLUMN_NAME"))
                                .put("type", cols.getString("TYPE_NAME"))
                                .put(
                                    "nullable",
                                    cols.getInt("NULLABLE") != DatabaseMetaData.columnNoNulls
                                );
                    }
                }
            }
            return json.createObjectNode().set("tables", tables);
        }
    }

    private Object parameter(JsonNode n) {
        if (n.isNull()) return null;
        if (n.isTextual()) return n.textValue();
        if (n.isBoolean()) return n.booleanValue();
        if (n.isIntegralNumber()) return new BigDecimal(n.bigIntegerValue());
        if (n.isNumber()) return n.decimalValue();
        if (dev.flow.core.NumericValues.isNumeric(n)) return dev.flow.core.NumericValues.number(n);
        throw new FlowFault(
            "VALIDATION_ERROR",
            400,
            "SQL parameter must be a scalar or typed number"
        );
    }

    private JsonNode normalize(Object v) {
        if (v == null) return NullNode.instance;
        if (v instanceof BigDecimal d) return dev.flow.core.NumericValues.encode(json, d);
        if (v instanceof BigInteger || v instanceof Long) {
            BigInteger i = new BigInteger(v.toString());
            if (i.abs().compareTo(BigInteger.valueOf(9007199254740991L)) > 0) return json
                .createObjectNode()
                .put("type", "integer")
                .put("value", i.toString());
        }
        if (v instanceof java.sql.Timestamp t) return TextNode.valueOf(t.toInstant().toString());
        if (v instanceof java.sql.Date d) return TextNode.valueOf(d.toLocalDate().toString());
        if (v instanceof java.sql.Time t) return TextNode.valueOf(t.toLocalTime().toString());
        if (v instanceof java.time.temporal.TemporalAccessor) return TextNode.valueOf(v.toString());
        return json.valueToTree(v);
    }

    public void close() {
        pools.values().forEach(HikariDataSource::close);
    }
}
