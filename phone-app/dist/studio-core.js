export function chooseRecordingType(supported) {
  return (
    [
      'video/mp4;codecs=avc1.42E01E,mp4a.40.2',
      'video/mp4',
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm',
    ].find((type) => supported(type)) || ''
  );
}

export function fitCamera(sourceWidth, sourceHeight, width, height) {
  const scale = Math.max(width / sourceWidth, height / sourceHeight);
  return {
    width: sourceWidth * scale,
    height: sourceHeight * scale,
    x: (width - sourceWidth * scale) / 2,
    y: (height - sourceHeight * scale) / 2,
  };
}

export function wrapCaption(text, maxWidth, measure, maxLines = 4) {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let line = '';
  for (const word of words) {
    if (line && measure(line + ' ' + word) > maxWidth) {
      lines.push(line);
      line = word;
    } else line += (line ? ' ' : '') + word;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines)
    return [...lines.slice(0, maxLines - 1), lines.slice(maxLines - 1).join(' ')];
  return lines;
}

export function buildPostText({ usedVoice = false, usedAssist = false } = {}) {
  return (
    'Built an experimental camera-only lip-reading app. ' +
    (usedVoice
      ? 'Mouth a sentence → predicted captions → an AI-generated voice. '
      : 'Live camera footage → predicted captions. ') +
    'No microphone input. ' +
    (usedAssist ? 'Model helps choose between possible readings. ' : '') +
    '#BuildInPublic'
  );
}
