# SurveySync Direct Tracker Endpoint

This replaces the Google Form transport and routes SurveySync support payloads. SurveySync saves every feedback report or error-log entry locally first, then sends a copy directly to the shared tracker. Feedback uses the **Intake** tab; diagnostics use the **Error Log** tab.

## One-time deployment

1. Open the **FieldBook Sync Feedback Tracker** Google Sheet.
2. Choose **Extensions → Apps Script**.
3. Replace the default `Code.gs` contents with the supplied `Code.gs` file.
4. Open **Project Settings** and confirm the V8 runtime is enabled (default).
5. Choose **Deploy → New deployment → Web app**.
6. Set **Execute as: Me** and **Who has access: Anyone**.
7. Deploy and authorize the script when Google asks.
8. Copy the deployed URL ending in `/exec`.
9. Put that URL in the repository `feedback.json` as `submit_url`. Once that is done, every v8.1.20+ installation can receive the endpoint automatically; no per-computer Google configuration is required.

## Tracker / Drive targets already configured in Code.gs

- Tracker spreadsheet ID: `1OvFje-9m8yFWTz6h73ZXmVcRdXKU6zRE6HQ2qPtlAa4`
- Intake sheet: `Intake`
- Error-log sheet: `Error Log`
- Feedback attachment folder ID: `1xV5kT5V1v8ZuI1zjR7NgP8eiy-7B5X3_`

## Behavior

- Duplicate local report IDs are idempotent: retrying the same `FBL-...` report returns the existing `FBR-...` intake ID instead of adding another row.
- Error-log payloads include `route: error_log` and append unique `SSE-...` events to the **Error Log** tab. Retrying the same event ID does not add a duplicate row.
- New tracker IDs use `FBR-####`.
- Selected support files and the privacy-safe diagnostic ZIP can be copied into the dedicated Drive attachment folder. Shared sync is capped at 10 MB; larger files remain in the local feedback folder.
- User-entered values are escaped before writing to Sheets to prevent spreadsheet-formula injection.
- The Intake row receives `Triage Status = New` and is not automatically promoted to the engineering `Requests` tab.


## SurveySync migration note

The v9.2.1 client ships the official tracker endpoint as a built-in fallback and prefers the SurveySync repository configuration over any legacy per-machine FieldBook Sync endpoint override. The server accepts both `FieldBook Sync` and `SurveySync` application identifiers for backward compatibility. After updating `Code.gs`, update the existing Web App deployment so the `/exec` URL remains unchanged.
