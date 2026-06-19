// ServiceNow Business Rule template (recommended trigger).
//
// Create: System Definition > Business Rules > New
//   Table:    Incident [incident]
//   When:     after
//   Insert:   true
//   Advanced: true
//
// Paste the function below as the script. It POSTs the new incident to the
// router's /sn/webhook endpoint. The router classifies and patches the same
// record, so do not block incident creation on this call.
//
// Store the endpoint URL and the shared token in sys_properties:
//   x_router.endpoint  = https://YOUR-CLOUD-RUN-URL/sn/webhook
//   x_router.token     = (the WEBHOOK_TOKEN value)

(function executeRule(current, previous /*null when async*/) {

    try {
        var endpoint = gs.getProperty('x_router.endpoint');
        var token = gs.getProperty('x_router.token');
        if (!endpoint) { return; }

        var body = {
            sys_id: current.getUniqueValue(),
            number: current.getValue('number'),
            short_description: current.getValue('short_description'),
            description: current.getValue('description')
        };

        var r = new sn_ws.RESTMessageV2();
        r.setEndpoint(endpoint);
        r.setHttpMethod('POST');
        r.setRequestHeader('Content-Type', 'application/json');
        r.setRequestHeader('X-Router-Token', token);
        r.setRequestHeader('X-Request-Id', current.getValue('number'));
        r.setRequestBody(JSON.stringify(body));
        // Short timeout; this should not slow down ticket creation.
        r.setHttpTimeout(10000);
        r.executeAsync();
    } catch (e) {
        gs.error('ticket-router business rule failed: ' + e);
    }

})(current, previous);
