// Claude Bridge — ExtendScript side. Loaded once when the panel starts.
// ExtendScript is ES3: no JSON object, so we carry a small serializer.

var CB = CB || {};

CB.stringify = function (v) {
  var t = typeof v;
  if (v === null || v === undefined) return 'null';
  if (t === 'number') return isFinite(v) ? String(v) : 'null';
  if (t === 'boolean') return v ? 'true' : 'false';
  if (t === 'string') {
    return '"' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
      .replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t')
      .replace(/[\x00-\x1f]/g, ' ') + '"';
  }
  if (v instanceof Array) {
    var a = [];
    for (var i = 0; i < v.length; i++) a.push(CB.stringify(v[i]));
    return '[' + a.join(',') + ']';
  }
  if (t === 'object') {
    var o = [];
    for (var k in v) {
      if (v.hasOwnProperty(k) && typeof v[k] !== 'function') o.push(CB.stringify(k) + ':' + CB.stringify(v[k]));
    }
    return '{' + o.join(',') + '}';
  }
  return CB.stringify(String(v));
};

CB.findItemByPath = function (bin, path) {
  for (var i = 0; i < bin.children.numItems; i++) {
    var c = bin.children[i];
    if (c.type === ProjectItemType.BIN) {
      var hit = CB.findItemByPath(c, path);
      if (hit) return hit;
    } else if (c.getMediaPath && c.getMediaPath() === path) {
      return c;
    }
  }
  return null;
};

// Premiere's Volume "Level" is linear with 0.17782794 == 0 dB.
CB.dbToLevel = function (db) { return Math.pow(10, (db - 15) / 20); };

/*
 * Build a project from an edit spec (see build_edit.py for the format), save it,
 * optionally export it. Returns a summary of what is on the timeline.
 */
CB.buildEdit = function (spec) {
  var f = new File(spec.project);
  if (f.exists) {
    if (!spec.overwrite) throw 'project already exists: ' + spec.project;
    f.remove();
  }
  if (!app.newProject(spec.project)) throw 'could not create project ' + spec.project;
  var proj = app.project;
  if (proj.path !== spec.project) throw 'new project did not become active (active: ' + proj.path + ')';
  var root = proj.rootItem;

  var mediaBin = root.createBin('Media');
  if (!proj.importFiles(spec.media, true, mediaBin, false)) throw 'import failed';
  var items = [];
  for (var i = 0; i < spec.media.length; i++) {
    var it = CB.findItemByPath(mediaBin, spec.media[i]);
    if (!it) throw 'imported file not found in project: ' + spec.media[i];
    items.push(it);
  }

  var seq = proj.createNewSequenceFromClips(spec.sequence_name || spec.name, [items[spec.sequence_from || 0]], root);
  if (!seq) throw 'could not create sequence';
  // createNewSequenceFromClips drops the whole clip on the timeline; start clean.
  var groups = [seq.videoTracks, seq.audioTracks];
  for (var g = 0; g < groups.length; g++) {
    for (var t = 0; t < groups[g].numTracks; t++) {
      var cl = groups[g][t].clips;
      for (var k = cl.numItems - 1; k >= 0; k--) cl[k].remove(false, false);
    }
  }

  var at = 0;
  for (var c = 0; c < spec.clips.length; c++) {
    var cs = spec.clips[c];
    var item = items[cs.media];
    var start = (cs.at !== undefined && cs.at !== null) ? cs.at : at;
    item.setInPoint(cs['in'], 4);
    item.setOutPoint(cs.out, 4);
    seq.videoTracks[cs.track || 0].overwriteClip(item, start);
    item.clearInPoint();
    item.clearOutPoint();
    at = start + (cs.out - cs['in']);
  }

  // Audio-only placements (e.g. a voiceover under silent slide clips): {media, in, out, at, track}
  var aud = spec.audio || [];
  for (var au = 0; au < aud.length; au++) {
    var ai = items[aud[au].media];
    if (aud[au]['in'] !== undefined) ai.setInPoint(aud[au]['in'], 4);
    if (aud[au].out !== undefined) ai.setOutPoint(aud[au].out, 4);
    seq.audioTracks[aud[au].track || 0].overwriteClip(ai, aud[au].at || 0);
    ai.clearInPoint();
    ai.clearOutPoint();
  }

  // Per-clip gain, matched by timeline start on A1 (clips are linked to V1).
  var aclips = seq.audioTracks[0].clips;
  for (var c2 = 0; c2 < spec.clips.length; c2++) {
    var gdb = spec.clips[c2].gain_db;
    if (gdb === undefined || gdb === null || gdb === 0) continue;
    if (c2 < aclips.numItems) {
      var comps = aclips[c2].components;
      for (var q = 0; q < comps.numItems; q++) {
        if (comps[q].displayName === 'Volume') {
          var props = comps[q].properties;
          for (var p = 0; p < props.numItems; p++) {
            if (props[p].displayName === 'Level') props[p].setValue(CB.dbToLevel(gdb), true);
          }
        }
      }
    }
  }

  var markers = spec.markers || [];
  for (var m = 0; m < markers.length; m++) {
    var mk = seq.markers.createMarker(markers[m].time);
    mk.name = markers[m].name || '';
    if (markers[m].comment) mk.comments = markers[m].comment;
  }

  var captionOk = null;
  if (spec.captions) {
    proj.importFiles([spec.captions], true, root, false);
    var capItem = CB.findItemByPath(root, spec.captions);
    if (!capItem) {
      var base = spec.captions.split('/').pop();
      for (var r = 0; r < root.children.numItems; r++) if (root.children[r].name === base) capItem = root.children[r];
    }
    captionOk = capItem ? seq.createCaptionTrack(capItem, 0, Sequence.CAPTION_FORMAT_SUBTITLE) : false;
  }

  proj.save();

  var exported = null;
  if (spec['export']) exported = seq.exportAsMediaDirect(spec['export'], spec.preset, app.encoder.ENCODE_ENTIRE);

  var timeline = [];
  var vc = seq.videoTracks[0].clips;
  for (var v = 0; v < vc.numItems; v++) {
    timeline.push({ name: vc[v].name, start: vc[v].start.seconds, end: vc[v].end.seconds, src_in: vc[v].inPoint.seconds, src_out: vc[v].outPoint.seconds });
  }
  var summary = {
    project: proj.path, sequence: seq.name, width: seq.frameSizeHorizontal, height: seq.frameSizeVertical,
    duration: seq.end / 254016000000, timeline: timeline, audio_clips: aclips.numItems,
    markers: seq.markers.numMarkers, captions: captionOk, exported: exported
  };
  if (spec.close !== false) proj.closeDocument(1, 0);
  return summary;
};

// Every job from the client is sent as CB.run(function(){ ... }).
CB.run = function (fn) {
  try {
    return '{"ok":true,"result":' + CB.stringify(fn()) + '}';
  } catch (e) {
    return '{"ok":false,"error":' + CB.stringify(String(e) + (e && e.line ? ' (line ' + e.line + ')' : '')) + '}';
  }
};
