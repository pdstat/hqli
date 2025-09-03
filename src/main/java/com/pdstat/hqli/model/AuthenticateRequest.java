package com.pdstat.hqli.model;

public class AuthenticateRequest {

    private Header header;

    private AuthenticatePayload payload;

    public Header getHeader() {
        return header;
    }

    public void setHeader(Header header) {
        this.header = header;
    }

    public AuthenticatePayload getPayload() {
        return payload;
    }

    public void setPayload(AuthenticatePayload payload) {
        this.payload = payload;
    }
}
