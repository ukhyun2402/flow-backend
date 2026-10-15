package dev.flow.db;

import dev.flow.core.FlowFault;
import java.util.Locale;
import net.sf.jsqlparser.parser.CCJSqlParserUtil;

/** SQL differences remain isolated here. Tibero behavior requires its own integration suite. */
public enum DatabaseDialect {
    MYSQL,
    ORACLE,
    TIBERO,
    H2;

    public static DatabaseDialect fromProduct(String name) {
        String n = name.toLowerCase(Locale.ROOT);
        if (n.contains("mysql")) return MYSQL;
        if (n.contains("oracle")) return ORACLE;
        if (n.contains("tibero")) return TIBERO;
        if (n.contains("h2")) return H2;
        throw new FlowFault("DB_ERROR", 400, "Unsupported database product");
    }

    public String limit(String sql, int rows) {
        try {
            String select = CCJSqlParserUtil.parse(sql).toString();
            return switch (this) {
                case MYSQL -> "SELECT * FROM (" + select + ") flow_limited LIMIT " + rows;
                case ORACLE, TIBERO -> "SELECT * FROM (" +
                    select +
                    ") flow_limited WHERE ROWNUM <= " +
                    rows;
                case H2 -> "SELECT * FROM (" +
                    select +
                    ") flow_limited FETCH FIRST " +
                    rows +
                    " ROWS ONLY";
            };
        } catch (Exception ex) {
            throw new FlowFault("VALIDATION_ERROR", 400, "Query cannot be limited safely");
        }
    }
}
