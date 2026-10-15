package dev.flow.core;

public class FlowFault extends RuntimeException {

    private final String code;
    private final int status;
    private final String category;

    public FlowFault(String code, int status, String message) {
        this(code, status, message, code);
    }

    public FlowFault(String code, int status, String message, String category) {
        super(message);
        this.code = code;
        this.status = status;
        this.category = category;
    }

    public String code() {
        return code;
    }

    public String category() {
        return category;
    }

    public int status() {
        return status;
    }
}
