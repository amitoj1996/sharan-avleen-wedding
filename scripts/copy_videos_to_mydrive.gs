/**
 * Google Apps Script — Copy wedding videos from Computers backup to My Drive
 * Uses trigger chaining to automatically resume after each 5.5-minute run.
 * Fully hands-free — just run startCopy() once.
 *
 * HOW TO USE:
 * 1. Go to https://script.google.com → new project → paste this code
 * 2. Click "Services" (+) → add "Drive API" (v3)
 * 3. Click Run → select "startCopy"
 * 4. Grant permissions when prompted
 * 5. Sit back — it runs automatically until all videos are copied
 * 6. Check the Execution Log or your email for completion notification
 *
 * OTHER FUNCTIONS:
 * - checkProgress() — See how far along the copy is
 * - generateNewDriveJson() — Run after copy is done to get new file IDs
 * - stopCopy() — Cancel the automatic trigger chain
 * - resetProgress() — Start fresh
 */

var GIRL_FOLDER_ID = '1V76_3Uo-KY8wKj0vLJ6iQmsyyL71WXML';
var BOY_FOLDER_ID  = '144sBhp9suoPpJZ8LnqplNq59el2ZnEOo';

var GIRL_FOLDERS = {
  'mehdi 21': 'mehdi',
  '21 jan shagan ok': 'shagan',
  '22 sangeet ok': 'sangeet',
  '23 date vatna': 'vatna',
  '24 jan wedding': 'wedding'
};

var BOY_FOLDERS = {
  '19 jan path ok 25 gb': 'path',
  '22 jan shagan ok 138 gb': 'shagan',
  '22 jan sangeet': 'sangeet',
  '23 jan vatna 56 gb ok': 'vatna',
  '24 jan wedding 428gb': 'wedding',
  '24 reception 374 gb ok': 'reception'
};

var DEST_ROOT_NAME = 'Wedding Videos (Streaming)';
var MAX_RUNTIME_MS = 5.5 * 60 * 1000; // 5.5 min safety margin
var TRIGGER_INTERVAL_MIN = 7; // re-run every 7 minutes

// ================================================================
// START / STOP
// ================================================================

/**
 * Run this once to start the copy process. It will auto-continue.
 */
function startCopy() {
  Logger.log('Starting video copy process...');
  Logger.log('This will run automatically until complete.');
  Logger.log('');

  // Clear any existing triggers
  clearTriggers_();

  // Do first batch
  copyBatch_();
}

/**
 * Stop the automatic copy process.
 */
function stopCopy() {
  clearTriggers_();
  Logger.log('Copy process stopped. Run startCopy() to resume.');
}

/**
 * Check current progress.
 */
function checkProgress() {
  var props = PropertiesService.getScriptProperties();
  var filesCopied = parseInt(props.getProperty('filesCopied') || '0');
  var filesSkipped = parseInt(props.getProperty('filesSkipped') || '0');
  var totalFiles = parseInt(props.getProperty('totalFiles') || '0');
  var currentEvent = props.getProperty('currentEvent') || 'not started';
  var isComplete = props.getProperty('copyComplete') === 'true';

  Logger.log('========================================');
  Logger.log('Copy Progress:');
  Logger.log('  Files copied: ' + filesCopied);
  Logger.log('  Files skipped (already exist): ' + filesSkipped);
  Logger.log('  Total processed: ' + (filesCopied + filesSkipped));
  if (totalFiles > 0) {
    var pct = ((filesCopied + filesSkipped) / totalFiles * 100).toFixed(1);
    Logger.log('  Total files to copy: ' + totalFiles);
    Logger.log('  Progress: ' + pct + '%');
  }
  Logger.log('  Currently processing: ' + currentEvent);
  Logger.log('  Status: ' + (isComplete ? '✅ COMPLETE' : '⏳ In progress'));
  Logger.log('========================================');
}

// ================================================================
// CORE COPY LOGIC
// ================================================================

function copyBatch_() {
  var startTime = new Date().getTime();
  var props = PropertiesService.getScriptProperties();

  // Check if already complete
  if (props.getProperty('copyComplete') === 'true') {
    Logger.log('✅ Copy already complete! Run generateNewDriveJson() to get new file IDs.');
    clearTriggers_();
    return;
  }

  // Create destination root
  var destRoot = getOrCreateFolder_(null, DEST_ROOT_NAME);

  // Build task list if not built yet
  var taskListJson = props.getProperty('taskList');
  var taskList;

  if (!taskListJson) {
    Logger.log('Building file list (first run)...');
    taskList = buildTaskList_();
    props.setProperty('taskList', JSON.stringify(taskList));
    props.setProperty('totalFiles', taskList.length.toString());
    props.setProperty('taskIndex', '0');
    props.setProperty('filesCopied', '0');
    props.setProperty('filesSkipped', '0');
    Logger.log('Found ' + taskList.length + ' video files to copy.');
  } else {
    taskList = JSON.parse(taskListJson);
  }

  var taskIndex = parseInt(props.getProperty('taskIndex') || '0');
  var filesCopied = parseInt(props.getProperty('filesCopied') || '0');
  var filesSkipped = parseInt(props.getProperty('filesSkipped') || '0');
  var sessionCopied = 0;

  Logger.log('Resuming from file ' + taskIndex + ' of ' + taskList.length);

  // Process files until time runs out
  while (taskIndex < taskList.length) {
    // Time check
    if (new Date().getTime() - startTime > MAX_RUNTIME_MS) {
      Logger.log('⏱️ Time limit reached. Will auto-continue...');
      break;
    }

    var task = taskList[taskIndex];
    props.setProperty('currentEvent', task.event + '_' + task.side);

    // Get or create destination folder
    var sideDest = getOrCreateFolder_(destRoot, task.side === 'girl' ? 'Girl Side' : 'Boy Side');
    var eventDest = getOrCreateFolder_(sideDest, task.event);

    // Check if file already exists in destination
    if (fileExistsInFolder_(eventDest.getId(), task.name)) {
      filesSkipped++;
      taskIndex++;
      continue;
    }

    // Copy file with retry + exponential backoff
    var copied = false;
    for (var attempt = 0; attempt < 5; attempt++) {
      try {
        Drive.Files.copy(
          { name: task.name, parents: [eventDest.getId()] },
          task.srcId,
          { supportsAllDrives: true }
        );
        filesCopied++;
        sessionCopied++;
        copied = true;

        if (sessionCopied % 10 === 0) {
          Logger.log('  Copied ' + sessionCopied + ' files this session (' + task.event + '_' + task.side + ')');
        }

        // Throttle: 2 seconds between copies to avoid rate limit
        Utilities.sleep(2000);
        break;
      } catch (e) {
        var msg = e.message.toLowerCase();
        if (msg.indexOf('rate limit') > -1 || msg.indexOf('user rate') > -1 || msg.indexOf('too many') > -1) {
          var waitSec = Math.pow(2, attempt + 1) * 5;
          Logger.log('  Rate limited: ' + task.name + ' — waiting ' + waitSec + 's (attempt ' + (attempt+1) + ')');
          Utilities.sleep(waitSec * 1000);
        } else if (msg.indexOf('daily limit') > -1 || msg.indexOf('quota') > -1 || msg.indexOf('storage') > -1) {
          Logger.log('');
          Logger.log('Hit 750GB daily transfer limit! Will resume in 24 hours.');
          props.setProperty('taskIndex', taskIndex.toString());
          props.setProperty('filesCopied', filesCopied.toString());
          props.setProperty('filesSkipped', filesSkipped.toString());
          scheduleLongTrigger_();
          return;
        } else {
          Logger.log('  ERROR: ' + task.name + ' — ' + e.message);
          break;
        }
      }
    }

    taskIndex++;
  }

  // Save progress
  props.setProperty('taskIndex', taskIndex.toString());
  props.setProperty('filesCopied', filesCopied.toString());
  props.setProperty('filesSkipped', filesSkipped.toString());

  var total = filesCopied + filesSkipped;
  var pct = (total / taskList.length * 100).toFixed(1);
  Logger.log('');
  Logger.log('Session: copied ' + sessionCopied + ' files');
  Logger.log('Overall: ' + total + ' / ' + taskList.length + ' (' + pct + '%)');

  // Check if done
  if (taskIndex >= taskList.length) {
    props.setProperty('copyComplete', 'true');
    clearTriggers_();
    Logger.log('');
    Logger.log('✅ ALL DONE! ' + filesCopied + ' videos copied to My Drive.');
    Logger.log('Next: run generateNewDriveJson() to get updated file IDs.');

    // Send email notification
    try {
      MailApp.sendEmail(
        Session.getActiveUser().getEmail(),
        'Wedding Videos Copy Complete',
        'All ' + filesCopied + ' wedding videos have been copied to your My Drive folder "' + DEST_ROOT_NAME + '".\n\nNext step: run generateNewDriveJson() in Apps Script to get the new file IDs.'
      );
      Logger.log('Email notification sent!');
    } catch (e) {}
  } else {
    // Schedule next run
    scheduleTrigger_();
    Logger.log('Next batch scheduled in ' + TRIGGER_INTERVAL_MIN + ' minutes.');
  }
}

// ================================================================
// BUILD TASK LIST
// ================================================================

function buildTaskList_() {
  var tasks = [];

  // Girl side
  tasks = tasks.concat(scanSideForVideos_(GIRL_FOLDER_ID, GIRL_FOLDERS, 'girl'));
  // Boy side
  tasks = tasks.concat(scanSideForVideos_(BOY_FOLDER_ID, BOY_FOLDERS, 'boy'));

  return tasks;
}

function scanSideForVideos_(parentId, folderMap, side) {
  var tasks = [];
  var subFolders = listFolders_(parentId);

  for (var i = 0; i < subFolders.length; i++) {
    var folder = subFolders[i];
    var folderNameLower = folder.name.toLowerCase();

    var eventId = null;
    for (var key in folderMap) {
      if (folderNameLower === key.toLowerCase()) {
        eventId = folderMap[key];
        break;
      }
    }
    if (!eventId) continue;

    Logger.log('  Scanning ' + side + '/' + eventId + '...');

    // Find Video/Videos subfolders
    var videoFolders = findVideoFolders_(folder.id);
    for (var j = 0; j < videoFolders.length; j++) {
      var videos = listVideoFiles_(videoFolders[j].id);
      for (var k = 0; k < videos.length; k++) {
        tasks.push({
          srcId: videos[k].id,
          name: videos[k].name,
          event: eventId,
          side: side
        });
      }
    }

    Logger.log('    Total tasks so far: ' + tasks.length);
  }

  return tasks;
}

function findVideoFolders_(parentId) {
  var result = [];
  var folders = listFolders_(parentId);
  for (var i = 0; i < folders.length; i++) {
    var name = folders[i].name.toUpperCase();
    if (name === 'VIDEO' || name === 'VIDEOS') {
      result.push(folders[i]);
      var subFolders = listFolders_(folders[i].id);
      for (var j = 0; j < subFolders.length; j++) {
        result.push(subFolders[j]);
      }
    }
  }
  return result;
}

// ================================================================
// HELPERS
// ================================================================

function listFolders_(parentId) {
  var folders = [];
  var pageToken = null;
  do {
    var r = Drive.Files.list({
      q: "'" + parentId + "' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
      fields: 'nextPageToken, files(id, name)',
      pageSize: 100,
      pageToken: pageToken,
      includeItemsFromAllDrives: true,
      supportsAllDrives: true
    });
    if (r.files) folders = folders.concat(r.files);
    pageToken = r.nextPageToken;
  } while (pageToken);
  return folders;
}

function listVideoFiles_(folderId) {
  var videos = [];
  var pageToken = null;
  do {
    var r = Drive.Files.list({
      q: "'" + folderId + "' in parents and (mimeType contains 'video/') and trashed = false",
      fields: 'nextPageToken, files(id, name, size)',
      pageSize: 1000,
      pageToken: pageToken,
      includeItemsFromAllDrives: true,
      supportsAllDrives: true
    });
    if (r.files) {
      for (var i = 0; i < r.files.length; i++) {
        videos.push({ id: r.files[i].id, name: r.files[i].name, size: r.files[i].size || '0' });
      }
    }
    pageToken = r.nextPageToken;
  } while (pageToken);
  return videos;
}

function fileExistsInFolder_(folderId, fileName) {
  var r = Drive.Files.list({
    q: "'" + folderId + "' in parents and name = '" + fileName.replace(/'/g, "\\'") + "' and trashed = false",
    fields: 'files(id)',
    pageSize: 1
  });
  return r.files && r.files.length > 0;
}

function getOrCreateFolder_(parent, name) {
  var query;
  if (parent) {
    query = "'" + parent.getId() + "' in parents and name = '" + name.replace(/'/g, "\\'") + "' and mimeType = 'application/vnd.google-apps.folder' and trashed = false";
  } else {
    query = "name = '" + name.replace(/'/g, "\\'") + "' and mimeType = 'application/vnd.google-apps.folder' and 'root' in parents and trashed = false";
  }
  var r = Drive.Files.list({ q: query, fields: 'files(id, name)', pageSize: 1 });
  if (r.files && r.files.length > 0) return DriveApp.getFolderById(r.files[0].id);
  if (parent) return parent.createFolder(name);
  return DriveApp.getRootFolder().createFolder(name);
}

// ================================================================
// TRIGGER MANAGEMENT
// ================================================================

function scheduleTrigger_() {
  clearTriggers_();
  ScriptApp.newTrigger('copyBatch_')
    .timeBased()
    .after(TRIGGER_INTERVAL_MIN * 60 * 1000)
    .create();
}

function scheduleLongTrigger_() {
  clearTriggers_();
  // Wait 24 hours for daily quota to reset
  ScriptApp.newTrigger('copyBatch_')
    .timeBased()
    .after(24 * 60 * 60 * 1000)
    .create();
  Logger.log('Scheduled to resume in 24 hours.');
}

function clearTriggers_() {
  var triggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < triggers.length; i++) {
    if (triggers[i].getHandlerFunction() === 'copyBatch_') {
      ScriptApp.deleteTrigger(triggers[i]);
    }
  }
}

// ================================================================
// POST-COPY: Generate new JSON with My Drive file IDs
// ================================================================

function generateNewDriveJson() {
  var destRoot = getOrCreateFolder_(null, DEST_ROOT_NAME);
  var result = { videos: {} };
  var totalVideos = 0;

  ['Girl Side', 'Boy Side'].forEach(function(sideName) {
    var side = sideName === 'Girl Side' ? 'girl' : 'boy';
    var sideFolder = getOrCreateFolder_(destRoot, sideName);
    var eventFolders = listFolders_(sideFolder.getId());

    for (var i = 0; i < eventFolders.length; i++) {
      var key = eventFolders[i].name + '_' + side;
      var videos = listVideoFiles_(eventFolders[i].id);
      result.videos[key] = videos;
      totalVideos += videos.length;
      Logger.log(key + ': ' + videos.length + ' videos');
    }
  });

  result.generated = new Date().toISOString();
  result.totalVideos = totalVideos;
  Logger.log('Total: ' + totalVideos + ' videos');

  var existing = DriveApp.getFilesByName('drive_videos_new.json');
  while (existing.hasNext()) existing.next().setTrashed(true);

  var file = DriveApp.createFile('drive_videos_new.json', JSON.stringify(result), 'application/json');
  Logger.log('Saved: ' + file.getUrl());
}

function resetProgress() {
  clearTriggers_();
  PropertiesService.getScriptProperties().deleteAllProperties();
  Logger.log('All progress reset. Run startCopy() to begin fresh.');
}
