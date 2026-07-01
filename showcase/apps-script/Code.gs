/**
 * NANDA Town Showcase backend, running as a Google Apps Script web app.
 *
 * Storage lives entirely in the owner's Google Drive:
 *   - a Google Sheet ("NANDA Town Showcase Submissions") holds every
 *     submission with a status column (pending / approved / rejected)
 *   - a Drive folder ("NANDA Showcase Uploads") holds uploaded video files,
 *     shared as anyone-with-link so the world can view them
 *
 * Endpoints (deploy as web app, execute as Me, access: Anyone):
 *   GET  ?action=approved                 public list for the showcase page
 *   GET  ?action=pending&admin_key=KEY    admin review queue
 *   POST {action:'submit', ...}           store a submission as pending
 *   POST {action:'approve', id, admin_key, register_in_town}
 *   POST {action:'reject', id, admin_key}
 *
 * On approve, the entry can also be registered in the NANDA Town skills
 * registry (nandatown.projectnanda.org/api/skills) server-side.
 */

var ADMIN_KEY = 'e44f959a9695b5d71bd29285';   // change any time, then redeploy
var TOWN_API = 'https://nandatown.projectnanda.org/api/skills';
var SHEET_TITLE = 'NANDA Town Showcase Submissions';
var UPLOADS_FOLDER = 'NANDA Showcase Uploads';
var HEADERS = ['id', 'status', 'submitted_at', 'approved_at', 'name', 'author',
               'description', 'submission_type', 'contributor_path', 'url',
               'content', 'endpoints', 'tags', 'town_registry_id'];
var TYPES = ['code', 'live', 'video', 'writeup'];
var PATHS = ['individual', 'startup', 'corporate'];

function getSheet_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('SHEET_ID');
  var ss;
  if (id) {
    ss = SpreadsheetApp.openById(id);
  } else {
    ss = SpreadsheetApp.create(SHEET_TITLE);
    props.setProperty('SHEET_ID', ss.getId());
  }
  var sh = ss.getSheets()[0];
  if (sh.getLastRow() === 0) sh.appendRow(HEADERS);
  return sh;
}

function getUploadsFolder_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('FOLDER_ID');
  if (id) return DriveApp.getFolderById(id);
  var folder = DriveApp.createFolder(UPLOADS_FOLDER);
  props.setProperty('FOLDER_ID', folder.getId());
  return folder;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function rowToObj_(row) {
  var o = {};
  for (var i = 0; i < HEADERS.length; i++) o[HEADERS[i]] = row[i] === '' ? null : row[i];
  return o;
}

function listByStatus_(status) {
  var sh = getSheet_();
  var last = sh.getLastRow();
  if (last < 2) return [];
  var rows = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();
  var out = [];
  for (var i = 0; i < rows.length; i++) {
    if (rows[i][1] === status) out.push(rowToObj_(rows[i]));
  }
  out.reverse();
  return out;
}

function findRowById_(id) {
  var sh = getSheet_();
  var last = sh.getLastRow();
  if (last < 2) return null;
  var ids = sh.getRange(2, 1, last - 1, 1).getValues();
  for (var i = 0; i < ids.length; i++) {
    if (String(ids[i][0]) === String(id)) return i + 2;   // sheet row number
  }
  return null;
}

function requireAdmin_(key) {
  if (!key || String(key) !== ADMIN_KEY) throw new Error('Invalid admin key.');
}

function doGet(e) {
  try {
    var p = (e && e.parameter) || {};
    if (p.action === 'approved') {
      var entries = listByStatus_('approved');
      return json_({ count: entries.length, approved: entries });
    }
    if (p.action === 'pending') {
      requireAdmin_(p.admin_key);
      var pend = listByStatus_('pending');
      return json_({ count: pend.length, pending: pend });
    }
    return json_({ service: 'nanda-showcase', storage: 'google-drive',
                   use: 'GET ?action=approved | POST {action: submit|approve|reject}' });
  } catch (err) {
    return json_({ error: String(err.message || err) });
  }
}

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.action === 'submit') return submit_(body);
    if (body.action === 'approve') return approve_(body);
    if (body.action === 'reject') return reject_(body);
    return json_({ error: "Unknown action. Use submit | approve | reject." });
  } catch (err) {
    return json_({ error: String(err.message || err) });
  }
}

function submit_(b) {
  if (TYPES.indexOf(b.submission_type) < 0) return json_({ error: 'submission_type must be one of ' + TYPES.join(' | ') });
  if (PATHS.indexOf(b.contributor_path) < 0) b.contributor_path = 'individual';
  if (!b.name || String(b.name).length < 2) return json_({ error: 'Give your project a name.' });
  if (!b.author || String(b.author).length < 2) return json_({ error: 'Tell us who you are.' });
  if (!b.description || String(b.description).length < 10) return json_({ error: 'The description needs at least a sentence.' });

  var url = b.url || null;

  // Optional direct video upload: {file_name, file_type, file_data (base64)}
  // is saved into the Drive uploads folder, shared anyone-with-link, and its
  // Drive URL becomes the entry URL.
  if (b.file_data && b.file_name) {
    var bytes = Utilities.base64Decode(b.file_data);
    if (bytes.length > 30 * 1024 * 1024) return json_({ error: 'Uploads are capped at 30 MB. Host bigger videos on YouTube or Drive and paste the link.' });
    var blob = Utilities.newBlob(bytes, b.file_type || 'application/octet-stream', b.file_name);
    var file = getUploadsFolder_().createFile(blob);
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    url = 'https://drive.google.com/file/d/' + file.getId() + '/view';
  }

  if ((b.submission_type === 'code' || b.submission_type === 'live' || b.submission_type === 'video')
      && !(url && String(url).indexOf('http') === 0)) {
    return json_({ error: 'A full http(s) URL is required for this submission type.' });
  }
  if (b.submission_type === 'writeup' && (!b.content || String(b.content).length < 50)) {
    return json_({ error: 'The written case needs some substance.' });
  }

  var id = Utilities.getUuid().replace(/-/g, '').slice(0, 12);
  getSheet_().appendRow([
    id, 'pending', new Date().toISOString(), '',
    b.name, b.author, b.description, b.submission_type, b.contributor_path,
    url || '', b.content || '', b.endpoints || '', b.tags || '', ''
  ]);
  return json_({ ok: true, id: id, status: 'pending', url: url,
                 note: 'Submitted for review. It appears on the public showcase once approved.' });
}

function approve_(b) {
  requireAdmin_(b.admin_key);
  var rowNum = findRowById_(b.id);
  if (!rowNum) return json_({ error: 'No submission with id ' + b.id });
  var sh = getSheet_();
  var row = sh.getRange(rowNum, 1, 1, HEADERS.length).getValues()[0];
  var rec = rowToObj_(row);

  var townResult = null;
  if (b.register_in_town !== false) {
    try {
      var payload = {
        name: rec.name, author: rec.author, description: rec.description,
        endpoints: rec.endpoints, tags: rec.tags,
        source_type: rec.submission_type === 'writeup' ? 'content'
                   : rec.submission_type === 'code' ? 'github' : 'url',
        source_url: rec.submission_type === 'writeup' ? null : rec.url,
        content: rec.submission_type === 'writeup' ? rec.content : null
      };
      var resp = UrlFetchApp.fetch(TOWN_API, {
        method: 'post', contentType: 'application/json',
        payload: JSON.stringify(payload), muteHttpExceptions: true
      });
      townResult = { status: resp.getResponseCode() };
      if (resp.getResponseCode() < 400) {
        var data = JSON.parse(resp.getContentText());
        var townId = data.id || (data.skill && data.skill.id) || '';
        if (townId) sh.getRange(rowNum, HEADERS.indexOf('town_registry_id') + 1).setValue(townId);
      }
    } catch (err) {
      townResult = { error: String(err.message || err).slice(0, 200) };
    }
  }

  sh.getRange(rowNum, HEADERS.indexOf('status') + 1).setValue('approved');
  sh.getRange(rowNum, HEADERS.indexOf('approved_at') + 1).setValue(new Date().toISOString());
  return json_({ ok: true, id: b.id, status: 'approved', town_registry: townResult,
                 note: 'Live on the showcase immediately.' });
}

function reject_(b) {
  requireAdmin_(b.admin_key);
  var rowNum = findRowById_(b.id);
  if (!rowNum) return json_({ error: 'No submission with id ' + b.id });
  getSheet_().getRange(rowNum, HEADERS.indexOf('status') + 1).setValue('rejected');
  return json_({ ok: true, id: b.id, status: 'rejected' });
}
