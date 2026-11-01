import { agentSummary } from './agent-core.js';
import { chooseRecordingType, fitCamera, wrapCaption, buildPostText } from './studio-core.js';
import { displayText } from './core.js';

export function createAudioEngine() {
  let context,
    destination,
    analyser,
    playing = 0;
  const sources = new Set();
  async function unlock() {
    if (!context) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (!AudioContext) throw new Error('Audio playback is unavailable in this browser.');
      context = new AudioContext();
      destination = context.createMediaStreamDestination();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
    }
    await context.resume();
    return destination.stream;
  }
  async function play(bytes) {
    await unlock();
    const audio = await context.decodeAudioData(bytes.slice(0));
    const source = context.createBufferSource();
    source.buffer = audio;
    source.connect(context.destination);
    source.connect(destination);
    source.connect(analyser);
    playing++;
    sources.add(source);
    return new Promise((resolve) => {
      source.onended = () => {
        playing--;
        sources.delete(source);
        source.disconnect();
        resolve();
      };
      source.start();
    });
  }
  function level() {
    if (!analyser || !playing) return 0;
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    return Math.sqrt(data.reduce((sum, v) => sum + v * v, 0) / data.length);
  }
  return {
    unlock,
    play,
    stop() {
      for (const source of sources) {
        try {
          source.stop();
        } catch {}
      }
    },
    level,
    get playing() {
      return playing > 0;
    },
  };
}

export function createStudio({
  video,
  getState,
  ensureCamera,
  stopCamera,
  requestAPI,
  audio,
  onRecordStart,
  onVisibility,
  onVoice,
  onCommit,
}) {
  const $ = (id) => document.getElementById(id);
  const canvas = $('studio-canvas'),
    ctx = canvas.getContext('2d', { alpha: false });
  const videoParent = video.parentElement,
    videoNext = video.nextSibling;
  let visible = false,
    vertical = window.innerWidth < 700,
    frameId,
    recorder,
    chunks = [],
    recordStarted = 0,
    stopTimer,
    recordStream,
    objectUrl;
  let countdown = false,
    exporting = false,
    usedVoice = false,
    usedAssist = false,
    recordingMetadata = {};
  canvas.width = vertical ? 720 : 1280;
  canvas.height = vertical ? 1280 : 720;
  canvas.parentElement.classList.toggle('vertical', vertical);
  $('studio-aspect').textContent = vertical ? '9:16 ↕' : '16:9 ↔';
  function message(text) {
    $('studio-status').textContent = text;
  }
  function pill(text, x, y, color = '#d3f5ae', fill = '#101e15dc') {
    ctx.font = '500 11px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    const width = ctx.measureText(text).width + 25;
    ctx.fillStyle = fill;
    ctx.beginPath();
    ctx.roundRect(x, y, width, 29, 7);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(text, x + 12, y + 19);
    return width;
  }
  function draw(now) {
    if (!visible && !recording()) return;
    const w = canvas.width,
      h = canvas.height,
      s = Math.min(w / 1280, h / 720),
      state = getState();
    const unit = vertical ? w / 720 : s;
    ctx.fillStyle = '#080d0e';
    ctx.fillRect(0, 0, w, h);
    let camera;
    if (video.readyState >= 2 && video.videoWidth) {
      camera = fitCamera(video.videoWidth, video.videoHeight, w, h);
      ctx.save();
      if (video.classList.contains('mirrored')) {
        ctx.translate(w, 0);
        ctx.scale(-1, 1);
      }
      ctx.drawImage(video, camera.x, camera.y, camera.width, camera.height);
      ctx.restore();
    } else {
      const gradient = ctx.createRadialGradient(w * 0.5, h * 0.4, 10, w * 0.5, h * 0.4, w * 0.7);
      gradient.addColorStop(0, '#24383b');
      gradient.addColorStop(1, '#090f13');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = '#9fb6b017';
      ctx.lineWidth = 1;
      const grid = 64 * unit;
      for (let x = 0; x < w; x += grid) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      for (let y = 0; y < h; y += grid) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }
    }
    const shade = ctx.createLinearGradient(0, 0, 0, h);
    shade.addColorStop(0, '#020807a0');
    shade.addColorStop(0.3, '#02080708');
    shade.addColorStop(0.6, '#02080720');
    shade.addColorStop(1, '#020807f0');
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, w, h);
    const margin = 42 * unit;
    ctx.save();
    ctx.scale(unit, unit);
    const pw = w / unit,
      ph = h / unit;
    ctx.fillStyle = '#f2f6ef';
    ctx.font = '600 26px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.fillText('lipread', 42, 54);
    ctx.fillStyle = '#a4bdad';
    ctx.font = '500 8px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.fillText('S T U D I O', 139, 53);
    pill(
      state.running ? 'LIVE CAMERA' : 'CAMERA OFF',
      42,
      73,
      state.running ? '#d3f5ae' : '#91a6a2',
    );
    if (state.phase) pill(state.phase, 42, 110, '#b9d6ff', '#112039de');
    if (recording()) {
      const seconds = Math.floor((now - recordStarted) / 1000);
      pill(
        '● REC  ' +
          String(Math.floor(seconds / 60)).padStart(2, '0') +
          ':' +
          String(seconds % 60).padStart(2, '0'),
        pw - 158,
        28,
        '#ffd1d2',
        '#4b1e26d9',
      );
      $('studio-record-label').textContent = 'Stop · ' + seconds + ' / 45s';
    } else pill('MIC OFF', pw - 112, 28, '#b9d0c3', '#0d1b19c9');
    const quality = state.quality;
    if (camera && quality?.landmarks && now - quality.at < 1500) {
      const mirrored = video.classList.contains('mirrored');
      const points = quality.landmarks.map(([x, y]) => [
        (camera.x + (mirrored ? 1 - x : x) * camera.width) / unit,
        (camera.y + y * camera.height) / unit,
      ]);
      ctx.strokeStyle = quality.ok ? '#d5f9af8c' : '#e9bf8b8c';
      ctx.lineWidth = 0.75;
      for (const [a, b] of [
        [0, 1],
        [0, 2],
        [1, 2],
        [2, 3],
      ]) {
        ctx.beginPath();
        ctx.moveTo(...points[a]);
        ctx.lineTo(...points[b]);
        ctx.stroke();
      }
      for (const [x, y] of points) {
        ctx.strokeStyle = '#d2f6b0';
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = '#e8ffca';
        ctx.fillRect(x - 1, y - 1, 2, 2);
      }
      const [mx, my] = points[3];
      ctx.strokeStyle = '#d5f9af70';
      ctx.beginPath();
      ctx.moveTo(mx + 10, my);
      ctx.lineTo(mx + 48, my);
      ctx.stroke();
      ctx.fillStyle = '#dcf8c5';
      ctx.font = '500 7px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      ctx.fillText('VISUAL LANDMARKS', mx + 53, my + 3);
    }
    if (state.agent) {
      const job = state.agent,
        cardWidth = vertical ? pw - 84 : 390,
        cardX = vertical ? 42 : pw - cardWidth - 42,
        cardY = vertical ? 165 : 125;
      ctx.font = '400 19px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      const reply = agentSummary(job);
      const replyLines = wrapCaption(reply, cardWidth - 32, (v) => ctx.measureText(v).width).slice(
        0,
        5,
      );
      ctx.fillStyle = '#0b180ee8';
      ctx.beginPath();
      ctx.roundRect(cardX, cardY, cardWidth, 60 + replyLines.length * 26, 12);
      ctx.fill();
      ctx.strokeStyle = '#658b4b70';
      ctx.stroke();
      ctx.fillStyle = '#bdda9a';
      ctx.font = '500 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      ctx.fillText(
        job.state === 'review'
          ? 'ACTION PREVIEW · CONFIRM TO EXECUTE'
          : job.state === 'completed'
            ? 'AGENT RESPONSE'
            : 'AGENT · ' + job.state.toUpperCase(),
        cardX + 16,
        cardY + 24,
      );
      ctx.fillStyle = '#e7f1dc';
      ctx.font = '400 19px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      replyLines.forEach((line, i) => ctx.fillText(line, cardX + 16, cardY + 54 + i * 26));
      $('studio-agent').textContent =
        job.state === 'review' ? 'Confirm action ↗' : 'Review request ↗';
    }
    const caption = state.caption;
    if (recording()) {
      usedVoice ||= audio.playing;
      usedAssist ||= caption?.source === 'MODEL SELECTED · UNVERIFIED';
    }
    let label = caption?.text ? caption.source : 'WAITING FOR PREDICTION';
    if (caption?.text && now - caption.at > 8000) label = 'LAST PREDICTION · ' + label;
    const maxWidth = vertical ? pw - 88 : Math.min(pw - 88, 960);
    let fontSize = vertical ? 48 : 49;
    const text = caption?.text
      ? displayText(caption.text)
      : state.running
        ? 'Your words will appear here.'
        : 'Sound off.\nWords on.';
    let lines = [];
    for (let attempt = 0; attempt < 8; attempt++) {
      ctx.font = '550 ' + fontSize + 'px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      lines = text
        .split('\n')
        .flatMap((t) => wrapCaption(t, maxWidth, (v) => ctx.measureText(v).width));
      if (lines.length <= 4 && lines.every((line) => ctx.measureText(line).width <= maxWidth))
        break;
      fontSize -= 4;
    }
    const lineHeight = fontSize * 1.2;
    const bottom = ph - 84;
    const top = bottom - lines.length * lineHeight;
    ctx.font = '500 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.fillStyle = '#bad694';
    ctx.fillText(label, 42, top - 22);
    ctx.fillStyle = caption?.source?.startsWith('DRAFT') ? '#dbe4df' : '#f3f8ef';
    ctx.font = '550 ' + fontSize + 'px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.shadowColor = '#0008';
    ctx.shadowBlur = 16;
    lines.forEach((line, i) => ctx.fillText(line, 42, top + (i + 1) * lineHeight - 8));
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#c1dac0';
    ctx.font = '500 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.fillText('CAMERA → TEXT' + (audio.playing ? ' → AI VOICE' : ''), 42, ph - 43);
    ctx.fillStyle = '#8b9f94';
    ctx.font = '400 8px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
    ctx.fillText('EXPERIMENTAL · PREDICTED CAPTIONS · NO MICROPHONE INPUT', 42, ph - 23);
    if (!vertical) {
      const info = audio.playing
        ? 'AI-GENERATED VOICE'
        : state.latency
          ? state.latency + 's PROCESSING'
          : 'ENGLISH / VISUAL ONLY';
      ctx.fillStyle = audio.playing ? '#d7f5a9' : '#91aaa0';
      ctx.font = '500 9px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif';
      ctx.textAlign = 'right';
      ctx.fillText(info, pw - 42, ph - 42);
      ctx.textAlign = 'left';
    }
    if (audio.playing) {
      const level = Math.min(1, audio.level() * 8);
      ctx.fillStyle = '#d7f5a9';
      ctx.fillRect(pw - 102, 75, Math.max(2, level * 60), 2);
    }
    ctx.restore();
    $('studio-camera').textContent = state.running ? 'Stop camera' : 'Start camera';
    $('studio-commit').disabled = !state.canCommit;
    $('studio-record').disabled = countdown || exporting;
    $('studio-voice').disabled = !state.provider || !state.caption?.text;
    frameId = requestAnimationFrame(draw);
  }
  function recording() {
    return recorder?.state === 'recording';
  }
  function enter() {
    visible = true;
    $('studio').hidden = false;
    document.body.classList.add('stage-open');
    canvas.parentElement.insertBefore(video, canvas);
    video.classList.add('studio-source-video');
    onVisibility(true);
    cancelAnimationFrame(frameId);
    frameId = requestAnimationFrame(draw);
    $('studio-close').focus();
  }
  function exit() {
    if (recording() || countdown) {
      message('Stop the recording before leaving Studio.');
      return;
    }
    visible = false;
    $('studio').hidden = true;
    document.body.classList.remove('stage-open');
    video.classList.remove('studio-source-video');
    videoParent.insertBefore(video, videoNext);
    cancelAnimationFrame(frameId);
    onVisibility(false);
    $('studio-open').focus();
  }
  async function record() {
    if (recording()) {
      stop();
      return;
    }
    if (countdown || exporting) return;
    try {
      if (!window.MediaRecorder || !canvas.captureStream)
        throw new Error('Recording is unavailable here. Try a current Chrome or Safari browser.');
      await audio.unlock();
      if (!(await ensureCamera()))
        throw new Error('Open your private connected link and start the camera first.');
      countdown = true;
      $('studio-countdown').hidden = false;
      for (let number = 3; number >= 1; number--) {
        $('studio-countdown').textContent = String(number);
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      $('studio-countdown').hidden = true;
      countdown = false;
      if (!getState().running)
        throw new Error('The camera stopped before recording. Start it and try again.');
      onRecordStart();
      usedVoice = usedAssist = false;
      recordStream = canvas.captureStream(30);
      const voiceStream = await audio.unlock();
      for (const track of voiceStream.getAudioTracks()) recordStream.addTrack(track.clone());
      const mimeType = chooseRecordingType((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(recordStream, {
        ...(mimeType ? { mimeType } : {}),
        videoBitsPerSecond: 3_000_000,
        audioBitsPerSecond: 96_000,
      });
      chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        message('Recording failed. Try another browser.');
        stop();
      };
      recorder.onstop = () => finishRecording(recorder.mimeType);
      recordStarted = performance.now();
      recorder.start(500);
      $('studio-record').classList.add('recording');
      message(
        'Recording your real camera and predicted captions. AI voice is included when played. Maximum 45 seconds.',
      );
      stopTimer = setTimeout(stop, 45000);
    } catch (error) {
      countdown = false;
      $('studio-countdown').hidden = true;
      message(error.message);
    }
  }
  function stop() {
    clearTimeout(stopTimer);
    if (recording()) recorder.stop();
    $('studio-record').classList.remove('recording');
    $('studio-record-label').textContent = 'Record clip';
  }
  async function finishRecording(mimeType) {
    const blob = new Blob(chunks, { type: mimeType || 'video/webm' });
    chunks = [];
    recordStream?.getTracks().forEach((track) => track.stop());
    recordStream = null;
    recordingMetadata = { usedVoice, usedAssist };
    exporting = true;
    message('Preparing your MP4. Keep this tab open…');
    $('studio-export').hidden = true;
    let output = blob,
      extension = mimeType.includes('mp4') ? 'mp4' : 'webm';
    try {
      const response = await requestAPI('/api/export', { body: blob, timeout: 80000, raw: true });
      output = await response.blob();
      extension = 'mp4';
      $('export-title').textContent = 'Your clip is ready.';
      $('export-note').textContent =
        'Real camera footage + predicted captions' +
        (usedVoice ? ' + AI-generated voice.' : '.') +
        ' No microphone input.';
      message('Clip ready. Download it, review the captions, and share when you’re happy with it.');
    } catch (error) {
      $('export-title').textContent = 'Original recording ready.';
      $('export-note').textContent =
        'MP4 conversion failed. Your original ' + extension.toUpperCase() + ' is available.';
      message(error.message);
    } finally {
      exporting = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = URL.createObjectURL(output);
      $('studio-download').href = objectUrl;
      $('studio-download').download = 'lipread-studio.' + extension;
      $('studio-download').textContent = 'Download ' + extension.toUpperCase() + ' ↧';
      $('studio-export').hidden = false;
      $('studio-record').disabled = false;
    }
  }
  $('studio-open').onclick = $('studio-open-bottom').onclick = enter;
  $('studio-close').onclick = exit;
  $('studio-camera').onclick = async () => {
    if (getState().running) stopCamera();
    else await ensureCamera();
  };
  $('studio-aspect').onclick = () => {
    if (recording() || countdown) {
      message('Stop recording before changing the format.');
      return;
    }
    vertical = !vertical;
    canvas.width = vertical ? 720 : 1280;
    canvas.height = vertical ? 1280 : 720;
    canvas.parentElement.classList.toggle('vertical', vertical);
    $('studio-aspect').textContent = vertical ? '9:16 ↕' : '16:9 ↔';
  };
  $('studio-record').onclick = record;
  $('studio-voice').onclick = onVoice;
  $('studio-commit').onclick = onCommit;
  $('studio-copy-post').onclick = async () => {
    try {
      await navigator.clipboard.writeText(buildPostText(recordingMetadata));
      message('Post text copied. Review it with your clip before sharing.');
    } catch {
      message('Clipboard access is unavailable in this browser.');
    }
  };
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && visible) exit();
  });
  return {
    enter,
    exit,
    get visible() {
      return visible;
    },
    onCameraStopped() {
      if (recording()) stop();
    },
    dispose() {
      stop();
      cancelAnimationFrame(frameId);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    },
  };
}
