/**
 * SurveySync direct feedback/error-log endpoint (FieldBook Sync backward compatible).
 * Deploy this script as a Web App:
 *   Execute as: Me
 *   Who has access: Anyone
 *
 * The desktop app writes its local append-only feedback log first, then POSTs a
 * validated JSON copy here. Feedback appends directly to the Intake sheet and
 * optionally stores explicitly selected support files in Drive. Error-log payloads
 * route to the Error Log sheet for support triage.
 */

const FBS_SPREADSHEET_ID = '1OvFje-9m8yFWTz6h73ZXmVcRdXKU6zRE6HQ2qPtlAa4';
const FBS_INTAKE_SHEET = 'Intake';
const FBS_ERROR_LOG_SHEET = 'Error Log';
const FBS_ATTACHMENT_ROOT_ID = '1xV5kT5V1v8ZuI1zjR7NgP8eiy-7B5X3_';
const FBS_SOURCE = 'SurveySync Feedback Wizard';
const FBS_ERROR_LOG_SOURCE = 'SurveySync Error Log';
const MAX_FILES = 6;
const MAX_TOTAL_FILE_BYTES = 10 * 1024 * 1024;

function jsonResponse_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return jsonResponse_({
    ok: true,
    service: 'SurveySync Feedback Intake',
    schema_version: 1,
    targets: [FBS_INTAKE_SHEET, FBS_ERROR_LOG_SHEET]
  });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(30000);
    const body = e && e.postData && e.postData.contents ? e.postData.contents : '';
    if (!body || body.length > 16 * 1024 * 1024) {
      throw new Error('Empty or oversized request.');
    }
    const payload = JSON.parse(body);
    if (!payload || payload.schema_version !== 1 || ['FieldBook Sync','SurveySync'].indexOf(String(payload.application || '')) < 0) {
      throw new Error('Unsupported SurveySync payload.');
    }
    const route = String(payload.route || 'feedback').toLowerCase();
    const targetSheet = String(payload.target_sheet || '').toLowerCase();
    if (route === 'error_log' || targetSheet === String(FBS_ERROR_LOG_SHEET).toLowerCase()) {
      return appendErrorLog_(payload);
    }
    if (route !== 'feedback' || (targetSheet && targetSheet !== String(FBS_INTAKE_SHEET).toLowerCase())) {
      throw new Error('Unsupported SurveySync payload route.');
    }

    const report = payload.report || {};
    validateReport_(report);

    const ss = SpreadsheetApp.openById(FBS_SPREADSHEET_ID);
    const sheet = ss.getSheetByName(FBS_INTAKE_SHEET);
    if (!sheet) throw new Error('Intake sheet not found.');

    // Idempotency: retries from the desktop must not create duplicate requests.
    const existing = findExistingByLocalId_(sheet, report.local_report_id);
    if (existing) {
      return jsonResponse_({
        ok: true,
        duplicate: true,
        intake_id: existing.intake_id,
        row: existing.row,
        attachment_folder_url: String(sheet.getRange(existing.row, 14).getDisplayValue() || '')
      });
    }

    const intakeId = nextIntakeId_(sheet);
    const attachment = saveFiles_(intakeId, report.local_report_id, payload.files || []);
    const skipped = Array.isArray(payload.skipped_files) ? payload.skipped_files.slice(0, 20) : [];
    let submitterNotes = String(report.submitter_notes || '');
    const context = [];
    if (report.project_name) context.push('Project: ' + report.project_name);
    if (report.job_state) context.push('Analysis: ' + report.job_state);
    if (report.provider) context.push('Engine: ' + report.provider);
    if (skipped.length) context.push('Not uploaded: ' + skipped.join(', '));
    if (context.length) submitterNotes = [submitterNotes, context.join(' | ')].filter(Boolean).join('\n');

    const row = [
      intakeId,
      safeCell_(report.submitted || new Date().toISOString()),
      '',
      safeCell_(report.requester || ''),
      safeCell_(report.type || ''),
      safeCell_(report.title || ''),
      safeCell_(report.description || ''),
      safeCell_(report.version || ''),
      safeCell_(report.priority || 'Normal'),
      safeCell_(report.severity || 'Not applicable'),
      safeCell_(report.steps || ''),
      safeCell_(report.expected || ''),
      safeCell_(report.actual || ''),
      attachment.folder_url || '',
      safeCell_(submitterNotes),
      'New',
      safeCell_(report.local_report_id || ''),
      FBS_SOURCE
    ];

    sheet.appendRow(row);
    const rowNumber = sheet.getLastRow();
    SpreadsheetApp.flush();

    return jsonResponse_({
      ok: true,
      intake_id: intakeId,
      row: rowNumber,
      attachment_folder_url: attachment.folder_url || '',
      attachment_count: attachment.count
    });
  } catch (err) {
    console.error(err && err.stack ? err.stack : err);
    return jsonResponse_({ok: false, error: String(err && err.message ? err.message : err)});
  } finally {
    try { lock.releaseLock(); } catch (_) {}
  }
}

function appendErrorLog_(payload) {
  const errors = Array.isArray(payload.errors) ? payload.errors.slice(0, 100) : [];
  if (!errors.length) throw new Error('Error Log payload has no errors.');

  const ss = SpreadsheetApp.openById(FBS_SPREADSHEET_ID);
  const sheet = ensureErrorLogSheet_(ss);
  let appended = 0;
  let firstRow = 0;
  errors.forEach(function(err) {
    const localId = String(err && err.error_id || '').trim();
    if (!/^SSE-[A-Za-z0-9-]{6,80}$/.test(localId)) return;
    if (findExistingErrorId_(sheet, localId)) return;
    const row = [
      safeCell_(localId),
      safeCell_(err.created_utc || ''),
      safeCell_(payload.submitted_utc || new Date().toISOString()),
      safeCell_(payload.app_version || ''),
      safeCell_(err.component || ''),
      safeCell_(err.code || ''),
      safeCell_(err.severity || ''),
      safeCell_(err.recoverable === false ? 'No' : 'Yes'),
      safeCell_(err.message || ''),
      safeCell_(String(err.detail || '').slice(-12000)),
      safeCell_(JSON.stringify(err.context || {})),
      safeCell_(JSON.stringify(err.sync || {})),
      FBS_ERROR_LOG_SOURCE
    ];
    sheet.appendRow(row);
    appended += 1;
    if (!firstRow) firstRow = sheet.getLastRow();
  });
  SpreadsheetApp.flush();
  return jsonResponse_({
    ok: true,
    route: 'error_log',
    error_log_id: appended ? 'ERR-' + String(firstRow).padStart(4, '0') : '',
    row: firstRow,
    received_count: errors.length,
    appended_count: appended
  });
}

function ensureErrorLogSheet_(ss) {
  let sheet = ss.getSheetByName(FBS_ERROR_LOG_SHEET);
  if (!sheet) {
    sheet = ss.insertSheet(FBS_ERROR_LOG_SHEET);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow([
      'Error ID',
      'Created UTC',
      'Submitted UTC',
      'App Version',
      'Component',
      'Code',
      'Severity',
      'Recoverable',
      'Message',
      'Detail',
      'Context JSON',
      'Sync JSON',
      'Source'
    ]);
  }
  return sheet;
}

function findExistingErrorId_(sheet, localId) {
  if (!localId || sheet.getLastRow() < 2) return null;
  const range = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1);
  return range.createTextFinder(String(localId)).matchEntireCell(true).findNext();
}

function validateReport_(r) {
  const allowed = ['Bug', 'Feature Request', 'Improvement', 'Question'];
  if (!/^FBL-[A-Za-z0-9-]{8,80}$/.test(String(r.local_report_id || ''))) {
    throw new Error('Invalid local report ID.');
  }
  if (allowed.indexOf(String(r.type || '')) < 0) throw new Error('Invalid report type.');
  if (String(r.title || '').trim().length < 3 || String(r.title || '').length > 180) {
    throw new Error('Invalid report title.');
  }
  if (String(r.description || '').trim().length < 5 || String(r.description || '').length > 12000) {
    throw new Error('Invalid report description.');
  }
  ['requester','version','priority','severity','steps','expected','actual','submitter_notes','project_name','job_state','provider']
    .forEach(function(k) {
      if (String(r[k] || '').length > 12000) throw new Error('Field too long: ' + k);
    });
}

function safeCell_(value) {
  let s = String(value == null ? '' : value);
  // Prevent formula injection when user-entered text is written to Sheets.
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function findExistingByLocalId_(sheet, localId) {
  if (!localId || sheet.getLastRow() < 2) return null;
  const range = sheet.getRange(2, 17, sheet.getLastRow() - 1, 1); // Q: Local Report ID
  const hit = range.createTextFinder(String(localId)).matchEntireCell(true).findNext();
  if (!hit) return null;
  const row = hit.getRow();
  return {row: row, intake_id: String(sheet.getRange(row, 1).getDisplayValue() || '')};
}

function nextIntakeId_(sheet) {
  const props = PropertiesService.getScriptProperties();
  let next = Number(props.getProperty('FBS_NEXT_FBR') || 0);
  if (!Number.isFinite(next) || next < 1) {
    next = 1;
    if (sheet.getLastRow() >= 2) {
      const ids = sheet.getRange(2, 1, sheet.getLastRow() - 1, 1).getDisplayValues();
      ids.forEach(function(row) {
        const m = /^FBR-(\d+)$/.exec(String(row[0] || '').trim());
        if (m) next = Math.max(next, Number(m[1]) + 1);
      });
    }
  }
  props.setProperty('FBS_NEXT_FBR', String(next + 1));
  return 'FBR-' + String(next).padStart(4, '0');
}

function saveFiles_(intakeId, localReportId, files) {
  if (!Array.isArray(files) || !files.length) return {count: 0, folder_url: ''};
  if (files.length > MAX_FILES) throw new Error('Too many support files.');
  let total = 0;
  files.forEach(function(f) {
    const n = Number(f && f.size_bytes || 0);
    if (!Number.isFinite(n) || n < 0) throw new Error('Invalid support-file size.');
    total += n;
  });
  if (total > MAX_TOTAL_FILE_BYTES) throw new Error('Support files exceed the 10 MB shared-sync limit.');

  const root = DriveApp.getFolderById(FBS_ATTACHMENT_ROOT_ID);
  const folderName = (intakeId + ' - ' + localReportId).replace(/[^A-Za-z0-9._()\- ]+/g, '_').slice(0, 160);
  const folder = root.createFolder(folderName);
  let count = 0;
  files.forEach(function(f, i) {
    if (!f || !f.data_base64) return;
    const name = String(f.name || ('attachment_' + (i + 1))).replace(/[\\/:*?"<>|]+/g, '_').slice(0, 180);
    const mime = String(f.content_type || 'application/octet-stream');
    const bytes = Utilities.base64Decode(String(f.data_base64));
    if (bytes.length !== Number(f.size_bytes || bytes.length)) throw new Error('Support-file size mismatch: ' + name);
    const blob = Utilities.newBlob(bytes, mime, name);
    const file = folder.createFile(blob);
    file.setDescription('SurveySync feedback support file for ' + intakeId + ' / ' + localReportId);
    count += 1;
  });
  return {count: count, folder_url: folder.getUrl()};
}
