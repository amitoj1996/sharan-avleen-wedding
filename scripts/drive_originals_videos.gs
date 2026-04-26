/**
 * Google Apps Script — List 4K original video file IDs
 *
 * Companion to drive_listing.gs. Scans the same Girl/Boy root folders
 * (which still contain the 4K originals) but emits ONLY video metadata,
 * so we can fold an `originalId` field into drive_photos.json without
 * touching the 1080p IDs that the streaming/Unraid path depends on.
 *
 * HOW TO USE:
 * 1. https://script.google.com → new project → paste this code
 * 2. Services (+) → Drive API (v3)
 * 3. Run → listOriginalVideos
 * 4. Download `originals_videos.json` from your Drive root
 * 5. Save it at the repo root, then run:
 *      python3 scripts/merge_original_ids.py originals_videos.json
 */

function listOriginalVideos() {
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

  var result = { videos: {} };
  var total = 0;

  total += processSide(GIRL_FOLDER_ID, GIRL_FOLDERS, 'girl', result);
  total += processSide(BOY_FOLDER_ID,  BOY_FOLDERS,  'boy',  result);

  result.generated = new Date().toISOString();
  result.totalVideos = total;

  Logger.log('Total original videos: ' + total);
  for (var key in result.videos) {
    Logger.log('  ' + key + ': ' + result.videos[key].length);
  }

  var jsonStr = JSON.stringify(result, null, 2);
  var existing = DriveApp.getFilesByName('originals_videos.json');
  while (existing.hasNext()) existing.next().setTrashed(true);
  var f = DriveApp.createFile('originals_videos.json', jsonStr, 'application/json');
  Logger.log('Saved: ' + f.getUrl());
}

function processSide(parentFolderId, folderMap, side, result) {
  var count = 0;
  var subFolders = listFolders(parentFolderId);
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
    if (!eventId) {
      Logger.log('  Skipping: ' + folder.name);
      continue;
    }
    var eventKey = eventId + '_' + side;
    if (!result.videos[eventKey]) result.videos[eventKey] = [];
    var videos = listVideosInFolder(folder.id);
    result.videos[eventKey] = result.videos[eventKey].concat(videos);
    count += videos.length;
    Logger.log('  ' + eventKey + ': ' + videos.length);
  }
  return count;
}

function listFolders(parentId) {
  var folders = [];
  var pageToken = null;
  do {
    var response = Drive.Files.list({
      q: "'" + parentId + "' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
      fields: 'nextPageToken, files(id, name)',
      pageSize: 100,
      pageToken: pageToken,
      includeItemsFromAllDrives: true,
      supportsAllDrives: true
    });
    if (response.files) folders = folders.concat(response.files);
    pageToken = response.nextPageToken;
  } while (pageToken);
  return folders;
}

function listVideosInFolder(eventFolderId) {
  var videos = [];
  var subFolders = listFolders(eventFolderId);
  for (var i = 0; i < subFolders.length; i++) {
    var subName = subFolders[i].name.toUpperCase();
    if (subName === 'VIDEO' || subName === 'VIDEOS') {
      videos = videos.concat(listVideoFilesRecursive(subFolders[i].id));
    }
  }
  return videos;
}

function listVideoFilesRecursive(folderId) {
  var videos = [];
  var pageToken = null;
  do {
    var response = Drive.Files.list({
      q: "'" + folderId + "' in parents and (mimeType contains 'video/') and trashed = false",
      fields: 'nextPageToken, files(id, name, size)',
      pageSize: 1000,
      pageToken: pageToken,
      includeItemsFromAllDrives: true,
      supportsAllDrives: true
    });
    if (response.files) {
      for (var i = 0; i < response.files.length; i++) {
        videos.push({
          id: response.files[i].id,
          name: response.files[i].name,
          size: response.files[i].size ? parseInt(response.files[i].size) : 0
        });
      }
    }
    pageToken = response.nextPageToken;
  } while (pageToken);
  var subFolders = listFolders(folderId);
  for (var j = 0; j < subFolders.length; j++) {
    videos = videos.concat(listVideoFilesRecursive(subFolders[j].id));
  }
  return videos;
}
