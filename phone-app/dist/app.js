import { createFramePacer } from './capture-pacer.js';
import { createAgentUI } from './agent-ui.js';
import {
  readConnection,
  framePacket,
  transcriptText,
  displayText,
  upsertCaption,
  compareWords,
  readingCandidates,
} from './core.js';
import { createStudio, createAudioEngine } from './studio.js';

const $ = (id) => document.getElementById(id);
const video = $('video');
const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d', { alpha: false });
const entries = [];
let connection,
  media,
  socket,
  captureTimer,
  heartbeat,
  progressTimer,
  pollTimer,
  overlayTimer,
  wakeLock;
let mode = 'live',
  facing = 'user',
  running = false,
  finishing = false,
  connecting = false,
  sending = false;
let encoding = false,
  captureStart = 0,
  segmentStart = 0,
  lastCapture = 0,
  lastMediaTime = -1;
let frameCount = 0,
  fpsStart = 0,
  callbackId,
  sessionId,
  activeDraft,
  restartAfterStop = false;
const finalized = new Set();
const capturePacer = createFramePacer(25);
let adaptingVideo = false;
let visualTurns = false,
  cameraSession = null,
  activeVisualTurn = 0,
  turnPhase = '',
  voiceEpoch = 0;
let providerReady = false,
  providerVoice = false,
  latestAgent = null,
  voiceBusy = false,
  studioCaption = null,
  studioQuality = null,
  studioLatency = null,
  stageCaptureTimer;
const assistBusy = new Set();
const audio = createAudioEngine();
const agentUI = createAgentUI({
  requestAPI,
  getLatest: () => entries.at(-1),
  onState: (job) => {
    latestAgent = job;
  },
  onSettings: () => openSettings(),
  onInterrupt: () => {
    voiceEpoch++;
    audio.stop();
    voiceBusy = false;
    refreshModelControls();
  },
  onLiveMode: (enabled) => {
    if (socket?.readyState === WebSocket.OPEN)
      socket.send(JSON.stringify({ type: 'conversation', enabled }));
  },
  onPhase: (value, text) => {
    turnPhase = text;
  },
});
const studio = createStudio({
  video,
  audio,
  getState: () => ({
    running,
    caption: studioCaption,
    quality: studioQuality,
    latency: studioLatency,
    provider: providerVoice,
    agent: latestAgent,
    phase:
      turnPhase ||
      (voiceBusy
        ? audio.playing
          ? 'AI VOICE PLAYBACK'
          : 'GENERATING AI VOICE'
        : assistBusy.size
          ? 'MODEL CONTEXT SELECTION'
          : ''),
    canCommit: running && !finishing && !$('commit').disabled,
  }),
  ensureCamera: ensureStudioCamera,
  stopCamera: () => stopCapture(),
  requestAPI,
  onCommit: commitSentence,
  onVoice: () => playEntry(entries.at(-1)),
  onRecordStart: () => {
    studioCaption = null;
  },
  onVisibility: (visible) => {
    clearInterval(stageCaptureTimer);
    if (visible)
      stageCaptureTimer = setInterval(() => captureFrame(performance.now(), video.currentTime), 20);
  },
});

function status(message, kind = '') {
  $('status-message').textContent = message;
  $('status-dot').className = 'status-indicator ' + kind;
}
function cameraHint(message, kind = '') {
  $('camera-hint').className = 'quality-label ' + kind;
  $('camera-hint').replaceChildren(
    document.createElement('span'),
    document.createTextNode(message),
  );
}
function savedConnection() {
  try {
    return JSON.parse(sessionStorage.getItem('lipread-connection') || '{}');
  } catch {
    return {};
  }
}
function saveConnection() {
  try {
    sessionStorage.setItem('lipread-connection', JSON.stringify(connection));
  } catch {}
}
function showConnection() {
  $('connection').hidden = false;
  $('server-input').value = connection?.server || location.origin;
  $('key-input').value = connection?.key || '';
}
try {
  connection = readConnection(location.hash, location.origin, savedConnection());
  saveConnection();
} catch (error) {
  status(error.message, 'error');
}
if (location.hash.includes('key='))
  history.replaceState(null, '', location.pathname + location.search);

async function checkStatus() {
  clearTimeout(pollTimer);
  if (!connection?.key) {
    showConnection();
    $('connection-state').textContent = 'Connect your device';
    status('Open your private phone link to get started.');
    return;
  }
  try {
    const response = await fetch(connection.server + '/api/status', {
      headers: { Authorization: 'Bearer ' + connection.key },
      signal: AbortSignal.timeout(10000),
      cache: 'no-store',
    });
    if (response.status === 401) {
      showConnection();
      throw new Error('Your access key has changed. Open the latest private link.');
    }
    if (!response.ok)
      throw new Error('Your computer is not reachable. Keep it awake and try again.');
    const data = await response.json();
    $('connection').hidden = true;
    $('connection-state').textContent =
      data.status === 'ready'
        ? 'Ready to read'
        : data.status === 'error'
          ? 'Unavailable'
          : 'Warming up';
    $('connection-state').classList.toggle('ready', data.status === 'ready');
    $('start').disabled = data.status !== 'ready' || connecting || finishing;
    $('engine-label').textContent =
      data.device === 'mps' ? 'Mac acceleration on' : 'Processed on your computer';
    if (!running && !finishing && !connecting)
      status(
        data.status === 'ready'
          ? 'Face the camera. Speak naturally. Your microphone stays off.'
          : data.detail,
        data.status === 'error' ? 'error' : data.status === 'loading' ? 'working' : '',
      );
    if (data.status === 'loading') pollTimer = setTimeout(checkStatus, 2000);
    if (data.status === 'ready') syncModel();
  } catch (error) {
    $('connection-state').textContent = 'Disconnected';
    $('connection-state').classList.remove('ready');
    if (!running) $('start').disabled = true;
    status(
      error.name === 'TimeoutError'
        ? 'Connection timed out. Keep your computer awake.'
        : error.message,
      'error',
    );
    pollTimer = setTimeout(checkStatus, 5000);
  }
}
$('connection-form').addEventListener('submit', (event) => {
  event.preventDefault();
  try {
    connection = readConnection('', $('server-input').value, { key: $('key-input').value.trim() });
    saveConnection();
    checkStatus();
  } catch (error) {
    status(error.message, 'error');
  }
});

function chooseMode(next) {
  if (running || connecting || finishing) return;
  mode = next;
  $('live-mode').setAttribute('aria-pressed', String(mode === 'live'));
  $('phrase-mode').setAttribute('aria-pressed', String(mode === 'phrase'));
  $('window-note').textContent = mode === 'live' ? 'Pause for a reply' : 'One phrase · up to 8s';
  $('commit').hidden = mode === 'phrase';
}
$('live-mode').onclick = () => chooseMode('live');
$('phrase-mode').onclick = () => chooseMode('phrase');

async function openCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
    throw new Error('Open the HTTPS link in Safari or Chrome to use the camera.');
  media = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      facingMode: { ideal: facing },
      width: { ideal: 1280 },
      height: { ideal: 720 },
      frameRate: { ideal: 30, max: 30 },
    },
  });
  video.srcObject = media;
  const actual = media.getVideoTracks()[0].getSettings().facingMode || facing;
  video.classList.toggle('mirrored', actual === 'user');
  await video.play();
  if (!video.videoWidth)
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error('The camera did not start. Try again.')),
        8000,
      );
      video.addEventListener(
        'loadedmetadata',
        () => {
          clearTimeout(timeout);
          resolve();
        },
        { once: true },
      );
    });
  $('camera-placeholder').hidden = true;
  $('face-guide').hidden = false;
}
function cameraError(error) {
  return (
    {
      NotAllowedError:
        'Camera access was denied. Allow Camera in your browser settings, then try again.',
      NotFoundError: 'No camera was found on this device.',
      NotReadableError: 'Your camera is busy. Close other camera apps and try again.',
      OverconstrainedError: 'This camera cannot use those settings. Try the other lens.',
    }[error.name] ||
    error.message ||
    'Could not open your camera.'
  );
}
async function startCapture() {
  if (running || connecting || finishing) return;
  if (!connection?.key) {
    showConnection();
    status('Open your private connected link before starting the camera.');
    return;
  }
  connecting = true;
  $('start').disabled = true;
  status('Opening your camera…', 'working');
  try {
    await openCamera();
    const url = new URL('/api/stream', connection.server);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(
        () => reject(new Error('The camera connection timed out.')),
        12000,
      );
      socket.onopen = () =>
        socket.send(
          JSON.stringify({
            token: connection.key,
            mode,
            conversation: $('agent-live-toggle').checked,
          }),
        );
      socket.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'connected') {
          visualTurns = Boolean(data.visual_turns);
          cameraSession = data.session_id;
          activeVisualTurn = 0;
          clearTimeout(timeout);
          resolve();
        }
        if (data.type === 'error') {
          clearTimeout(timeout);
          reject(new Error(data.message));
        }
      };
      socket.onerror = () => {
        clearTimeout(timeout);
        reject(new Error('Could not connect the camera stream.'));
      };
      socket.onclose = () => {
        clearTimeout(timeout);
        reject(new Error('The connection was closed. Try again.'));
      };
    });
    running = sending = true;
    connecting = finishing = false;
    sessionId = String(Date.now());
    captureStart = segmentStart = fpsStart = performance.now();
    frameCount = 0;
    capturePacer.reset(performance.now());
    adaptingVideo = false;
    lastCapture = 0;
    lastMediaTime = -1;
    activeDraft = null;
    finalized.clear();
    studioCaption = null;
    studioQuality = null;
    socket.onmessage = receive;
    socket.onclose = () => {
      const unexpected = running || finishing;
      restartAfterStop = false;
      cleanup();
      if (unexpected) {
        status('Connection lost. Tap start to reconnect.', 'error');
        checkStatus();
      }
    };
    socket.onerror = () => status('Your camera connection was interrupted.', 'error');
    media.getVideoTracks()[0].onended = () => stopCapture();
    $('start').disabled = false;
    $('start').classList.add('running');
    $('start-label').textContent = mode === 'live' ? 'Stop reading' : 'Finish phrase';
    $('capture-state').replaceChildren(
      document.createElement('span'),
      document.createTextNode('LIVE CAMERA'),
    );
    $('capture-state').classList.add('active');
    $('live-mode').disabled = $('phrase-mode').disabled = true;
    $('commit').disabled = false;
    $('flip').disabled = false;
    cameraHint('Checking your framing…');
    status('Start speaking. Draft words will appear as the model reads.', 'working');
    if ('requestVideoFrameCallback' in video) {
      const nextFrame = (now, metadata) => {
        if (!sending) return;
        captureFrame(now, metadata.mediaTime);
        callbackId = video.requestVideoFrameCallback(nextFrame);
      };
      callbackId = video.requestVideoFrameCallback(nextFrame);
    } else {
      captureTimer = setInterval(() => captureFrame(performance.now(), video.currentTime), 20);
    }
    progressTimer = setInterval(updateProgress, 100);
    heartbeat = setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }));
    }, 8000);
    try {
      wakeLock = await navigator.wakeLock?.request('screen');
    } catch {}
  } catch (error) {
    cleanup();
    status(cameraError(error), 'error');
    $('start').disabled = false;
  }
}
function captureFrame(now, mediaTime) {
  if (
    !sending ||
    encoding ||
    video.readyState < 2 ||
    mediaTime === lastMediaTime ||
    socket?.readyState !== WebSocket.OPEN ||
    !capturePacer.due(now)
  )
    return;
  if (socket.bufferedAmount > 180000) {
    adaptingVideo = true;
    status('Adapting video delivery to keep the camera live.');
    return;
  }
  if (adaptingVideo) {
    adaptingVideo = false;
    status('Video delivery recovered. Keep speaking naturally.');
  }
  lastCapture = now;
  lastMediaTime = mediaTime;
  const scale = Math.min(1, 800 / Math.max(video.videoWidth, video.videoHeight));
  const w = Math.round(video.videoWidth * scale),
    h = Math.round(video.videoHeight * scale);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  ctx.drawImage(video, 0, 0, w, h);
  encoding = true;
  canvas.toBlob(
    (blob) => {
      encoding = false;
      if (!blob || !sending || socket?.readyState !== WebSocket.OPEN) return;
      socket.send(framePacket((now - captureStart) / 1000, blob));
      frameCount++;
      if (now - fpsStart >= 1000) {
        const fps = Math.round((frameCount * 1000) / (now - fpsStart));
        $('fps').textContent = fps + ' fps';
        if (fps < 15)
          status(
            'Camera delivery is slow. Keep this tab open and improve the connection.',
            'error',
          );
        fpsStart = now;
        frameCount = 0;
      }
    },
    'image/jpeg',
    0.9,
  );
}
function updateProgress() {
  if (!running) return;
  const elapsed = (performance.now() - segmentStart) / 1000;
  $('capture-progress').style.width = Math.min(100, (elapsed / 8) * 100) + '%';
  if (mode === 'phrase' && (performance.now() - captureStart) / 1000 >= 7.8) stopCapture();
}
function setOverlay(text, label) {
  studioCaption = { text, source: label, at: performance.now(), id: studioCaption?.id };
  $('overlay-text').textContent = displayText(text);
  $('overlay-label').textContent = label;
  $('caption-overlay').hidden = false;
  clearTimeout(overlayTimer);
  if (label === 'REFINED')
    overlayTimer = setTimeout(() => {
      $('caption-overlay').hidden = true;
    }, 6000);
}
function receive(event) {
  let data;
  try {
    data = JSON.parse(event.data);
  } catch {
    return;
  }
  if (data.type === 'speech_activity') {
    if (data.event === 'started') activeVisualTurn = data.turn_id;
    agentUI.speech(data);
  } else if (data.type === 'utterance') {
    const entry = {
      ...data,
      type: 'result',
      id: sessionId + ':turn:' + data.turn_id,
      time: new Date(),
      cameraSession: sessionId,
    };
    for (let i = entries.length - 1; i >= 0; i--)
      if (entries[i].cameraSession === sessionId && entries[i].turn_id === data.turn_id)
        entries.splice(i, 1);
    upsertCaption(entries, entry);
    renderCaptions();
    compareReference(entry);
    agentUI.offerCaption(entry);
    if (data.turn_id >= activeVisualTurn && data.auto_send !== false)
      setOverlay(data.text, 'YOUR REQUEST');
    if (data.auto_send !== false && providerVoice && $('auto-voice').checked) playEntry(entry);
  } else if (data.type === 'quality') {
    studioQuality = { ...data, at: performance.now() };
    cameraHint(data.message, data.ok ? 'good' : 'warning');
    $('face-guide').classList.toggle('good', data.ok);
    if (data.box && running) positionGuide(data.box);
  } else if (data.type === 'draft') {
    if (finalized.has(data.sequence) || (visualTurns && data.turn_id < activeVisualTurn)) return;
    activeDraft = data.sequence;
    $('transcript-empty').hidden = true;
    $('draft-card').hidden = false;
    $('draft-phase').textContent = 'Live draft';
    $('draft-text').textContent = displayText(data.text);
    setOverlay(data.text, 'DRAFT · MAY CHANGE');
    studioCaption.id = sessionId + ':' + data.sequence;
    studioLatency = data.processing_seconds.toFixed(2);
    $('latency').textContent =
      Math.max(0, (performance.now() - captureStart) / 1000 - data.capture_end).toFixed(2) +
      's last frame → draft';
    status('Reading… Draft words may change as you keep speaking.', 'working');
    scrollCaptions();
  } else if (data.type === 'processing') {
    $('draft-phase').textContent = 'Refining phrase';
    status('Refining this phrase with more context…', 'working');
    $('commit').disabled = true;
  } else if (data.type === 'result') {
    finalized.add(data.sequence);
    const entry = {
      ...data,
      id: sessionId + ':' + data.sequence,
      time: new Date(),
      cameraSession: sessionId,
    };
    upsertCaption(entries, entry);
    renderCaptions();
    if (activeDraft === data.sequence) {
      activeDraft = null;
      $('draft-card').hidden = true;
    }
    if (data.auto_send === false) {
      $('caption-overlay').hidden = true;
      studioCaption = null;
      cameraHint('Unclear reading · keep speaking or correct it', 'warning');
    } else if (!data.visual_turns || data.turn_id >= activeVisualTurn)
      setOverlay(data.text, data.awaiting_pause ? 'LISTENING · CONTINUE YOUR REQUEST' : 'REFINED');
    if (studioCaption) studioCaption.id = entry.id;
    studioLatency = data.processing_seconds.toFixed(2);
    if (Number.isFinite(data.capture_end)) segmentStart = captureStart + data.capture_end * 1000;
    $('latency').textContent = data.processing_seconds.toFixed(2) + 's phrase processing';
    status(
      running
        ? 'Phrase captured. The agent will reply automatically when live replies are on.'
        : 'Your phrase is ready.',
    );
    compareReference(entry);
    if (!data.visual_turns) agentUI.offerCaption(entry);
    $('commit').disabled = !running;
    refreshModelControls();
    if (
      !data.visual_turns &&
      entry.auto_send !== false &&
      providerReady &&
      $('assist-toggle').checked
    )
      assistEntry(entry, true);
    else if (
      !data.visual_turns &&
      entry.auto_send !== false &&
      providerReady &&
      $('auto-voice').checked
    )
      playEntry(entry);
  } else if (data.type === 'abstained') {
    finalized.add(data.sequence);
    if (activeDraft === data.sequence) {
      activeDraft = null;
      $('draft-card').hidden = true;
    }
    $('caption-overlay').hidden = true;
    studioCaption = null;
    if (Number.isFinite(data.capture_end)) segmentStart = captureStart + data.capture_end * 1000;
    if (!data.silent) status(data.message, 'error');
    else status('Listening for your next phrase.');
  } else if (data.type === 'guidance' || data.type === 'error') {
    status(data.message, 'error');
  } else if (data.type === 'ready') {
    $('commit').disabled = !running;
  } else if (data.type === 'phrase_limit') {
    if (!finishing) stopCapture();
  } else if (data.type === 'finished') {
    const restart = restartAfterStop;
    restartAfterStop = false;
    cleanup();
    if (restart) startCapture();
    else
      status(
        entries.length
          ? 'Reading paused. Your captions stay here until you clear them.'
          : 'Try a complete phrase with your face clearly visible.',
      );
  }
}
function positionGuide(box) {
  const w = video.clientWidth,
    h = video.clientHeight;
  if (!w || !h || !video.videoWidth) return;
  const scale = Math.max(w / video.videoWidth, h / video.videoHeight);
  const fullW = video.videoWidth * scale,
    fullH = video.videoHeight * scale;
  const x = video.classList.contains('mirrored') ? 1 - box[0] - box[2] : box[0];
  const left = x * fullW - (fullW - w) / 2,
    top = box[1] * fullH - (fullH - h) / 2;
  const guide = $('face-guide');
  guide.style.left = Math.max(6, left) + 'px';
  guide.style.top = Math.max(6, top) + 'px';
  guide.style.width = Math.min(box[2] * fullW, w - Math.max(6, left) - 6) + 'px';
  guide.style.height = Math.min(box[3] * fullH, h - Math.max(6, top) - 6) + 'px';
}
function renderCaptions() {
  $('transcript-empty').hidden = entries.length > 0 || !$('draft-card').hidden;
  $('transcript').replaceChildren();
  for (const entry of entries) {
    const article = document.createElement('article');
    article.className = 'caption-entry';
    const meta = document.createElement('div');
    meta.className = 'entry-meta';
    const tag = document.createElement('span');
    tag.className = 'refined';
    tag.textContent = entry.auto_send === false ? 'Unclear · not sent' : 'Refined phrase';
    const time = document.createElement('time');
    time.textContent = entry.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    meta.append(tag, time);
    const text = document.createElement('p');
    text.textContent = displayText(entry.assist?.text || entry.text);
    article.append(meta, text);
    if (entry.assist) {
      tag.textContent = 'Model-selected reading';
      const source = document.createElement('div');
      source.className = 'entry-source ai';
      source.textContent =
        'AI context selection · unverified. Visual model: “' + displayText(entry.text) + '”';
      article.append(source);
    }
    if (entry.alternatives?.length) {
      const other = document.createElement('details');
      other.className = 'alternatives';
      const summary = document.createElement('summary');
      summary.textContent = 'Other possible readings';
      other.append(summary);
      for (const candidate of entry.alternatives) {
        const p = document.createElement('p');
        p.textContent = displayText(candidate);
        other.append(p);
      }
      article.append(other);
    }
    const tools = document.createElement('div');
    tools.className = 'entry-tools';
    const assist = document.createElement('button');
    assist.textContent = assistBusy.has(entry.id) ? 'Selecting…' : 'Compare readings';
    assist.disabled =
      !providerReady || assistBusy.has(entry.id) || readingCandidates(entry).length < 2;
    assist.onclick = () => assistEntry(entry);
    const voice = document.createElement('button');
    voice.textContent = 'AI voice ↗';
    voice.disabled = !providerVoice || voiceBusy;
    voice.onclick = () => playEntry(entry);
    const ask = document.createElement('button');
    ask.textContent = 'Review for agent ↗';
    ask.onclick = () => agentUI.review(entry);
    tools.append(ask, assist, voice);
    article.append(tools);
    $('transcript').append(article);
  }
  $('copy').disabled = $('clear').disabled = !entries.length;
  scrollCaptions();
}
function scrollCaptions() {
  const scroll = $('transcript-scroll');
  scroll.scrollTop = scroll.scrollHeight;
}
function compareReference(entry = entries.at(-1)) {
  const reference = $('reference-text').value;
  if (!entry || !reference.trim()) {
    $('accuracy-result').textContent = 'Your next refined caption will be compared here.';
    return;
  }
  const score = compareWords(reference, entry.text);
  $('accuracy-result').textContent = score
    ? score.errors +
      ' word edit' +
      (score.errors === 1 ? '' : 's') +
      ' across ' +
      score.words +
      ' reference words (' +
      Math.round(score.wer * 100) +
      '% word error rate). One phrase is not an overall accuracy measurement.'
    : 'Enter a sentence containing words to compare.';
}
function stopMedia() {
  studio.onCameraStopped();
  sending = false;
  clearInterval(captureTimer);
  clearInterval(progressTimer);
  if (callbackId !== undefined && video.cancelVideoFrameCallback)
    video.cancelVideoFrameCallback(callbackId);
  callbackId = undefined;
  media?.getTracks().forEach((track) => track.stop());
  media = null;
  video.srcObject = null;
  $('camera-placeholder').hidden = false;
  $('face-guide').hidden = true;
  $('capture-state').classList.remove('active');
  $('capture-state').replaceChildren(
    document.createElement('span'),
    document.createTextNode('CAMERA OFF'),
  );
  $('capture-progress').style.width = '0';
  wakeLock?.release().catch(() => {});
  wakeLock = null;
}
function stopCapture() {
  if (!running || finishing) return;
  finishing = true;
  running = false;
  stopMedia();
  $('start').disabled = true;
  $('flip').disabled = true;
  $('commit').disabled = true;
  $('start-label').textContent = 'Finishing phrase…';
  status('Refining the final words…', 'working');
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'finish' }));
  else {
    cleanup();
    status('The connection closed before the phrase finished.', 'error');
  }
}
function cleanup() {
  running = finishing = connecting = false;
  stopMedia();
  clearInterval(heartbeat);
  if (socket) {
    socket.onclose = null;
    socket.onerror = null;
    socket.close();
    socket = null;
  }
  $('start').classList.remove('running');
  $('start-label').textContent = 'Start conversation';
  $('start').disabled = false;
  $('flip').disabled = false;
  $('commit').disabled = true;
  $('live-mode').disabled = $('phrase-mode').disabled = false;
  $('draft-card').hidden = true;
  $('transcript-empty').hidden = entries.length > 0;
}
$('start').onclick = () => (running ? stopCapture() : startCapture());
function commitSentence() {
  if (running && socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'commit' }));
    $('commit').disabled = true;
    status('Finishing this sentence. Your camera stays on.', 'working');
  }
}
$('commit').onclick = commitSentence;
$('camera-interrupt').onclick = () => agentUI.interrupt();
$('flip').onclick = () => {
  if (connecting || finishing) return;
  facing = facing === 'user' ? 'environment' : 'user';
  if (running) {
    restartAfterStop = true;
    stopCapture();
  } else cameraHint(facing === 'user' ? 'Front camera selected' : 'Rear camera selected');
};
$('copy').onclick = async () => {
  try {
    await navigator.clipboard.writeText(
      transcriptText(
        entries.map((entry) => ({ ...entry, text: entry.assist?.text || entry.text })),
      ),
    );
    $('copy').setAttribute('aria-label', 'Copied transcript');
    status('Transcript copied.');
  } catch {
    status('Select the caption text to copy it.', 'error');
  }
};
$('clear').onclick = () => {
  entries.length = 0;
  studioCaption = null;
  renderCaptions();
  $('caption-overlay').hidden = true;
  compareReference();
  refreshModelControls();
};
$('details-toggle').onclick = () => {
  const open = $('details').hidden;
  $('details').hidden = !open;
  $('details-toggle').setAttribute('aria-expanded', String(open));
};
function openSettings() {
  $('settings-dialog').showModal();
}
$('settings-button').onclick = openSettings;
$('pairing-provider').onclick = () => {
  openSettings();
  $('provider-section').scrollIntoView({ block: 'start' });
};
$('accuracy-button').onclick = () => {
  openSettings();
  $('reference-text').focus();
};
$('settings-close').onclick = () => $('settings-dialog').close();
$('settings-dialog').addEventListener('click', (event) => {
  if (event.target === $('settings-dialog')) $('settings-dialog').close();
});
$('reference-text').addEventListener('input', () => compareReference());
document.addEventListener('visibilitychange', () => {
  if (document.hidden && running) {
    restartAfterStop = false;
    stopCapture();
  }
});
window.addEventListener('pagehide', () => {
  clearTimeout(pollTimer);
  clearInterval(stageCaptureTimer);
  studio.dispose();
  cleanup();
});

async function ensureStudioCamera() {
  if (mode === 'phrase' && running) {
    stopCapture();
    const until = performance.now() + 20000;
    while (finishing && performance.now() < until)
      await new Promise((resolve) => setTimeout(resolve, 100));
    if (finishing) return false;
  }
  if (!running) {
    chooseMode('live');
    await startCapture();
  }
  return running;
}

async function requestAPI(path, { body, method = 'POST', raw = false, timeout = 22000 } = {}) {
  if (!connection?.key) throw new Error('Open your private connected app link first.');
  const headers = { Authorization: 'Bearer ' + connection.key };
  if (body !== undefined && !raw) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(connection.server + path, {
      method,
      headers,
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
      cache: 'no-store',
    });
  } catch (error) {
    throw new Error(
      error.name === 'TimeoutError'
        ? 'The request timed out. Try again.'
        : 'Cannot reach your computer. Keep it awake and connected.',
    );
  }
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {}
    throw new Error(typeof detail === 'string' ? detail : 'The request could not finish.');
  }
  return response;
}
function providerMessage(text, error = false) {
  $('provider-message').textContent = text;
  $('provider-message').classList.toggle('error', error);
}
function refreshModelControls() {
  $('provider-state').textContent = providerReady ? 'Model connected' : 'Not connected';
  $('assist-toggle').disabled = !providerReady;
  $('auto-voice').disabled = !providerVoice;
  $('provider-forget').hidden = !providerReady;
  $('voice-latest').disabled = !providerVoice || !entries.length || voiceBusy;
  $('provider-connect').disabled = !connection?.key;
}
async function syncModel() {
  try {
    const response = await requestAPI('/api/provider/config', { method: 'GET' });
    const config = await response.json();
    providerReady = Boolean(config.configured);
    providerVoice = Boolean(config.voice_available);
    $('provider-protocol').value = config.protocol;
    $('provider-base').value = config.base_url;
    $('provider-model').value = config.model;
    agentUI.connect();
    refreshModelControls();
    renderCaptions();
  } catch {
    providerReady = providerVoice = false;
    refreshModelControls();
  }
}
$('provider-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const key = $('provider-key').value.trim();
  $('provider-key').value = '';
  $('provider-connect').disabled = true;
  providerMessage('Checking your model connection…');
  try {
    const response = await requestAPI('/api/provider/config', {
      body: {
        key,
        protocol: $('provider-protocol').value,
        base_url: $('provider-base').value.trim(),
        model: $('provider-model').value.trim(),
      },
    });
    const config = await response.json();
    providerReady = Boolean(config.configured);
    providerVoice = Boolean(config.voice_available);
    $('provider-protocol').value = config.protocol;
    $('provider-base').value = config.base_url;
    $('provider-model').value = config.model;
    agentUI.connect();
    providerMessage('Model connected. Review a caption and send it to the agent.');
    renderCaptions();
  } catch (error) {
    providerMessage(error.message, true);
  } finally {
    refreshModelControls();
  }
});
$('provider-forget').onclick = async () => {
  try {
    await requestAPI('/api/provider/config', { method: 'DELETE' });
    providerReady = providerVoice = false;
    $('assist-toggle').checked = $('auto-voice').checked = false;
    refreshModelControls();
    renderCaptions();
    providerMessage('Model key forgotten for this server session.');
  } catch (error) {
    providerMessage(error.message, true);
  }
};
$('auto-voice').addEventListener('change', async () => {
  if ($('auto-voice').checked)
    try {
      await audio.unlock();
      providerMessage('Refined captions will be read in an AI-generated voice.');
    } catch (error) {
      $('auto-voice').checked = false;
      providerMessage(error.message, true);
    }
});
$('assist-toggle').addEventListener('change', () => {
  providerMessage(
    $('assist-toggle').checked
      ? 'Context assist is on. Refined caption candidates will be sent to Model.'
      : 'Context assist is off.',
  );
});
async function assistEntry(entry, automatic = false) {
  if (!entry || !providerReady || assistBusy.has(entry.id)) return;
  const candidates = readingCandidates(entry);
  if (candidates.length < 2) {
    if (automatic && $('auto-voice').checked) playEntry(entry);
    return;
  }
  assistBusy.add(entry.id);
  renderCaptions();
  try {
    const previous = entries
      .slice(
        0,
        entries.findIndex((item) => item.id === entry.id),
      )
      .slice(-3)
      .map((item) => item.assist?.text || item.text)
      .join('\n')
      .slice(-1600);
    const response = await requestAPI('/api/provider/assist', {
      body: { candidates, context: previous },
    });
    const selection = await response.json();
    if (!entries.includes(entry)) return;
    if (!candidates.includes(selection.text))
      throw new Error('The AI selection did not match a visual reading.');
    entry.assist = selection;
    if (studioCaption?.id === entry.id) {
      setOverlay(selection.text, 'MODEL SELECTED · UNVERIFIED');
      studioCaption.id = entry.id;
    }
    providerMessage('Model selected an existing visual reading. It has not verified the words.');
    if (automatic && $('auto-voice').checked && entries.at(-1) === entry) playEntry(entry);
  } catch (error) {
    providerMessage(error.message, true);
    status(error.message, 'error');
    if (automatic && $('auto-voice').checked && entries.at(-1) === entry) playEntry(entry);
  } finally {
    assistBusy.delete(entry.id);
    renderCaptions();
  }
}
async function playEntry(entry) {
  if (!entry || !providerVoice || voiceBusy) return;
  const epoch = ++voiceEpoch;
  voiceBusy = true;
  refreshModelControls();
  renderCaptions();
  try {
    await audio.unlock();
    const text = entry.assist?.text || entry.text;
    providerMessage('Generating an AI voice for this predicted caption…');
    const response = await requestAPI('/api/provider/voice', { body: { text }, timeout: 40000 });
    const bytes = await response.arrayBuffer();
    if (epoch !== voiceEpoch) return;
    if (!entries.includes(entry)) return;
    setOverlay(text, entry.assist ? 'AI VOICE · AI-SELECTED TEXT' : 'AI VOICE · PREDICTED TEXT');
    studioCaption.id = entry.id;
    providerMessage('Playing AI-generated speech. No microphone input.');
    await audio.play(bytes);
    providerMessage('AI voice finished.');
  } catch (error) {
    if (epoch === voiceEpoch) {
      providerMessage(error.message, true);
      status(error.message, 'error');
    }
  } finally {
    if (epoch === voiceEpoch) voiceBusy = false;
    refreshModelControls();
    renderCaptions();
  }
}
$('voice-latest').onclick = () => playEntry(entries.at(-1));
refreshModelControls();
checkStatus();
$('studio-agent').onclick = () => agentUI.review(entries.at(-1), true);
if (new URLSearchParams(location.search).has('studio')) studio.enter();
