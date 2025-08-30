package com.pdstat.hqli.model;

public class CheckAgentResponse {

    private Payload payload;

    private MessageInfo msgInfo;

    public Payload getPayload() {
        return payload;
    }

    public void setPayload(Payload payload) {
        this.payload = payload;
    }

    public MessageInfo getMsgInfo() {
        return msgInfo;
    }

    public void setMsgInfo(MessageInfo msgInfo) {
        this.msgInfo = msgInfo;
    }
}
