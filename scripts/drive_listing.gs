/**
 * Google Apps Script — List all photos AND videos in wedding Drive folders
 * Uses Advanced Drive Service (works with "Computers" backup folders)
 *
 * HOW TO USE:
 * 1. Go to https://script.google.com
 * 2. Create a new project, paste this code
 * 3. Click "Services" (+) in the left sidebar → add "Drive API" (v3)
 * 4. Click Run → select "listAllMedia"
 * 5. Grant permissions when prompted
 * 6. Check Execution Log — it will say where the output file was saved
 * 7. Download "drive_photos.json" from your Drive root
 * 8. Save as: assets/data/drive_photos.json
 */

function listAllMedia() {
  var GIRL_FOLDER_ID = '1V76_3Uo-KY8wKj0vLJ6iQmsyyL71WXML';
  var BOY_FOLDER_ID  = '144sBhp9suoPpJZ8LnqplNq59el2ZnEOo';

  // Subfolder name → event ID mapping (case-insensitive matching)
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

  var result = { events: {}, videos: {} };
  var totalPhotos = 0;
  var totalVideos = 0;

  // Process girl side
  Logger.log('Processing Girl Side...');
  var girlCounts = processSide(GIRL_FOLDER_ID, GIRL_FOLDERS, 'girl', result);
  totalPhotos += girlCounts.photos;
  totalVideos += girlCounts.videos;

  // Process boy side
  Logger.log('Processing Boy Side...');
  var boyCounts = processSide(BOY_FOLDER_ID, BOY_FOLDERS, 'boy', result);
  totalPhotos += boyCounts.photos;
  totalVideos += boyCounts.videos;

  // Add metadata
  result.generated = new Date().toISOString();
  result.totalPhotos = totalPhotos;
  result.totalVideos = totalVideos;

  Logger.log('=================================');
  Logger.log('Total photos: ' + totalPhotos);
  Logger.log('Total videos: ' + totalVideos);
  Logger.log('');
  Logger.log('Photos per event:');
  for (var key in result.events) {
    Logger.log('  ' + key + ': ' + result.events[key].length);
  }
  Logger.log('Videos per event:');
  for (var key in result.videos) {
    Logger.log('  ' + key + ': ' + result.videos[key].length);
  }

  // Save to Drive
  var jsonStr = JSON.stringify(result);
  Logger.log('JSON size: ' + (jsonStr.length / 1024 / 1024).toFixed(2) + ' MB');

  // Delete old file if exists
  var existing = DriveApp.getFilesByName('drive_photos.json');
  while (existing.hasNext()) {
    existing.next().setTrashed(true);
  }

  var outputFile = DriveApp.createFile('drive_photos.json', jsonStr, 'application/json');
  Logger.log('Output saved to: ' + outputFile.getUrl());
  Logger.log('Download it and save as assets/data/drive_photos.json');
}

function processSide(parentFolderId, folderMap, side, result) {
  var photosCount = 0;
  var videosCount = 0;

  // List subfolders using Advanced Drive Service
  var subFolders = listFolders(parentFolderId);
  Logger.log('  Found ' + subFolders.length + ' subfolders');

  for (var i = 0; i < subFolders.length; i++) {
    var folder = subFolders[i];
    var folderNameLower = folder.name.toLowerCase();

    // Match folder name to event ID
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

    // Initialize arrays
    if (!result.events[eventKey]) result.events[eventKey] = [];
    if (!result.videos[eventKey]) result.videos[eventKey] = [];

    Logger.log('  Scanning: ' + folder.name + ' → ' + eventKey);

    // Scan for photos (skip Video folders)
    var photos = listFilesRecursive(folder.id, 'photos');
    result.events[eventKey] = result.events[eventKey].concat(photos);
    photosCount += photos.length;
    Logger.log('    Photos: ' + photos.length);

    // Scan for videos (only in Video/Videos folders)
    var videos = listVideosInFolder(folder.id);
    result.videos[eventKey] = result.videos[eventKey].concat(videos);
    videosCount += videos.length;
    Logger.log('    Videos: ' + videos.length);
  }

  return { photos: photosCount, videos: videosCount };
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

    if (response.files) {
      folders = folders.concat(response.files);
    }
    pageToken = response.nextPageToken;
  } while (pageToken);

  return folders;
}

/**
 * List photos recursively, SKIPPING Video/Videos folders
 */
function listFilesRecursive(folderId, mode) {
  var files = [];
  var pageToken = null;
  var mimeQuery = "(mimeType contains 'image/jpeg')";

  // List files in this folder
  do {
    var response = Drive.Files.list({
      q: "'" + folderId + "' in parents and " + mimeQuery + " and trashed = false",
      fields: 'nextPageToken, files(id, name)',
      pageSize: 1000,
      pageToken: pageToken,
      includeItemsFromAllDrives: true,
      supportsAllDrives: true
    });

    if (response.files) {
      for (var i = 0; i < response.files.length; i++) {
        files.push({
          id: response.files[i].id,
          name: response.files[i].name
        });
      }
    }
    pageToken = response.nextPageToken;
  } while (pageToken);

  // Recurse into subfolders (skip Video/Videos)
  var subFolders = listFolders(folderId);
  for (var j = 0; j < subFolders.length; j++) {
    var subName = subFolders[j].name.toUpperCase();
    if (subName === 'VIDEO' || subName === 'VIDEOS') {
      continue;
    }
    var subFiles = listFilesRecursive(subFolders[j].id, mode);
    files = files.concat(subFiles);
  }

  return files;
}

/**
 * Find Video/Videos subfolders and list video files inside them recursively
 */
function listVideosInFolder(eventFolderId) {
  var videos = [];

  // Find Video/Videos subfolders
  var subFolders = listFolders(eventFolderId);
  for (var i = 0; i < subFolders.length; i++) {
    var subName = subFolders[i].name.toUpperCase();
    if (subName === 'VIDEO' || subName === 'VIDEOS') {
      // Scan this folder and all its subfolders for video files
      var vids = listVideoFilesRecursive(subFolders[i].id);
      videos = videos.concat(vids);
    }
  }

  return videos;
}

/**
 * List video files recursively within a folder
 */
function listVideoFilesRecursive(folderId) {
  var videos = [];
  var pageToken = null;

  // List video files (MP4, MOV, AVI, MKV)
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

  // Recurse into subfolders
  var subFolders = listFolders(folderId);
  for (var j = 0; j < subFolders.length; j++) {
    var subVids = listVideoFilesRecursive(subFolders[j].id);
    videos = videos.concat(subVids);
  }

  return videos;
}
