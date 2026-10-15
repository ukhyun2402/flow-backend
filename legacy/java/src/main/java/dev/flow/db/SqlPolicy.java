package dev.flow.db;

import dev.flow.core.FlowFault;
import net.sf.jsqlparser.parser.CCJSqlParserUtil;
import net.sf.jsqlparser.statement.delete.Delete;
import net.sf.jsqlparser.statement.insert.Insert;
import net.sf.jsqlparser.statement.select.Select;
import net.sf.jsqlparser.statement.update.Update;

public final class SqlPolicy {

    private SqlPolicy() {}

    public static void check(String sql, boolean command) {
        if (
            sql == null || sql.length() > 100000 || sql.contains("${") || sql.contains("#{")
        ) throw invalid();
        try {
            var statements = CCJSqlParserUtil.parseStatements(sql).getStatements();
            if (statements.size() != 1) throw invalid();
            var s = statements.get(0);
            if (
                command
                    ? !(s instanceof Insert || s instanceof Update || s instanceof Delete)
                    : !(s instanceof Select)
            ) throw invalid();
        } catch (Exception ex) {
            throw invalid();
        }
    }

    private static FlowFault invalid() {
        return new FlowFault("VALIDATION_ERROR", 400, "Unsupported SQL statement");
    }
}
