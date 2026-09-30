# Vapi configuration

Use fictional information only. The repository contains no provider private key.

1. Deploy the API at an HTTPS address and confirm `/health` returns `{"status":"ok"}`.
2. In Vapi, create a **Custom Credential** under Integrations → Server Configuration. Choose Bearer Token, header `Authorization`, Include Bearer Prefix on. Enter the same value as backend `VAPI_WEBHOOK_SECRET`. Save its credential ID.
3. Create three stored Function tools from the objects in `vapi-tools.json`. Replace `https://YOUR_PUBLIC_API_HOST/voice/webhook` with your domain and each `credentialId` placeholder with the credential ID. Keep `async:false` and `timeoutSeconds:10`.
4. Create a stored assistant from `vapi-assistant.json` (or copy `system-prompt.md` into its system prompt). Replace the three tool ID placeholders with your saved tool IDs. Choose available provider voice/transcriber settings in your account. Default model is Vapi-managed OpenAI `gpt-4o-mini`.
5. Set backend `VAPI_PUBLIC_KEY` (public web SDK key, not private API key) and `VAPI_ASSISTANT_ID`. Redeploy. Browser voice requires HTTPS or localhost and microphone permission.
6. Test with the dashboard's start-call button or Vapi's dashboard tester. For telephone delivery, assign a Vapi number to this stored assistant. A web call is enough to verify voice interaction; do not claim a phone number exists unless assigned.

**Use stored tools and a stored assistant, referenced by ID.** Vapi withholds saved credential auth for server URLs supplied through transient assistant/assistantOverrides in call/chat/session requests (documented change effective September 23, 2026). Never work around this by putting a secret in browser code.

## Wire contract and consent

Vapi posts `message.type="tool-calls"`, `message.call.id`, and `message.toolCallList[]` containing `id`, `function.name`, and `function.arguments` (object, with string JSON tolerated). The endpoint responds:

```json
{"results":[{"toolCallId":"tool-call-id","result":"{\"status\":\"collecting\"}"}]}
```

Tool errors instead contain a JSON-encoded string `error`; never both result and error. Each response ID matches its request. Non-tool lifecycle events are safely acknowledged without storing a patient.

Confirmation checks the newest unfiltered user entry in `message.artifact.messages`: `role:"user"`, `message`, and numeric `endTime` or `time`. It must be newer than the last user message captured at review, match the tool's exact quoted confirmation, and be an entire explicit affirmative. Phrases such as “yes, but change my phone” do not qualify. Missing transcript data fails closed. The live schema supplies these fields; **verify their presence in an actual call for your account**. `artifactPlan.transcriptPlan.enabled=false` disables stored transcripts, not the expected live tool-call artifact. If your configuration omits live artifacts, investigate provider settings rather than bypassing consent.

The server can bind a review and consent to a revision; it cannot independently guarantee that every word was audibly played. The prompt instructs the model to read the complete deterministic readback and wait. Validate this in the live demo.

## Troubleshooting

- 401 webhook: check stored tool URL, credential selection, Bearer prefix, and exact shared secret
- 503: the relevant backend secret is missing; configure it and restart
- `CONFIRMATION_TRANSCRIPT_REQUIRED`: inspect the live tool request shape and timestamps; run a fresh review then ask a fresh “yes”
- `NEW_CONFIRMATION_REQUIRED`: assistant tried saving without a new answer after review
- `REVIEW_REQUIRED`: details were edited or reset; run review again
- `SAVE_UNAVAILABLE`: storage failed; retry identical confirmation arguments and do not announce success
- Button unavailable: set both browser public key and stored assistant ID on backend, then refresh

Official references: [Custom tools](https://docs.vapi.ai/tools/custom-tools), [Function vs API request tools](https://docs.vapi.ai/tools/api-request-vs-function), [Server authentication](https://docs.vapi.ai/server-url/server-authentication), [Web SDK](https://docs.vapi.ai/sdk/web).
