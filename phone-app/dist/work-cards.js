export function safePageURL(value) {
  try {
    const url = new URL(value);
    if (
      !['https:', 'http:'].includes(url.protocol) ||
      url.username ||
      url.password ||
      !url.hostname
    )
      return null;
    return url.href;
  } catch {
    return null;
  }
}

export function createWorkCards() {
  let urls = [];
  const $ = (id) => document.getElementById(id);
  function node(tag, className, text) {
    const el = document.createElement(tag);
    el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function link(url, title) {
    const a = node('a', 'source-link', title);
    a.href = url;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  }
  function download(text, title) {
    const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
    urls.push(url);
    const a = node('a', 'work-download', 'Download Markdown ↓');
    a.href = url;
    a.download =
      (title
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .slice(0, 60) || 'lipread-work') + '.md';
    return a;
  }
  function cited(report) {
    const p = node('div', 'research-body');
    const chars = Array.from(report.text);
    let cursor = 0;
    const citations = [...report.citations].sort((a, b) => a.start - b.start);
    for (const citation of citations) {
      const url = safePageURL(citation.url);
      if (!url || citation.start < cursor || citation.end > chars.length) continue;
      p.append(document.createTextNode(chars.slice(cursor, citation.start).join('')));
      const a = link(url, chars.slice(citation.start, citation.end).join('') || '[source]');
      a.title = citation.title;
      p.append(a);
      cursor = citation.end;
    }
    p.append(document.createTextNode(chars.slice(cursor).join('')));
    return p;
  }
  function card(receipt) {
    const result = receipt.result;
    if (receipt.tool === 'research') {
      const article = node('section', 'work-card research-card');
      article.append(node('span', 'work-kicker', 'WEB RESEARCH · SOURCED'), cited(result));
      const sources = node('div', 'work-sources');
      const seen = new Set();
      for (const citation of result.citations) {
        const url = safePageURL(citation.url);
        if (url && !seen.has(url)) {
          seen.add(url);
          sources.append(link(url, citation.title));
        }
      }
      article.append(
        sources,
        download(
          result.text + '\n\nSources\n' + [...seen].map((url) => '- ' + url).join('\n'),
          'Research notes',
        ),
      );
      return article;
    }
    if (receipt.tool === 'draft_document') {
      const article = node('section', 'work-card');
      article.append(node('span', 'work-kicker', 'GENERATED DRAFT'), node('h3', '', result.title));
      const preview = node(
        'p',
        'draft-excerpt',
        result.markdown.slice(0, 260) + (result.markdown.length > 260 ? '…' : ''),
      );
      article.append(preview);
      const open = node('button', 'work-open', 'View draft ↗');
      open.onclick = () => {
        $('work-title').textContent = result.title;
        $('work-content').textContent = result.markdown;
        $('work-dialog').showModal();
      };
      article.append(open, download(result.markdown, result.title));
      return article;
    }
    if (receipt.tool === 'open_page') {
      const url = safePageURL(result.url);
      if (!url) return null;
      const article = node('section', 'work-card');
      article.append(node('span', 'work-kicker', 'PAGE PREVIEW'), node('h3', '', result.title));
      const frame = document.createElement('iframe');
      frame.src = url;
      frame.title = result.title;
      frame.loading = 'lazy';
      frame.referrerPolicy = 'no-referrer';
      frame.setAttribute('sandbox', 'allow-scripts allow-forms');
      article.append(frame);
      article.append(
        node(
          'p',
          'preview-note',
          'Some sites block embedded previews. Use the link to open the page.',
        ),
        link(url, 'Open page ↗'),
      );
      return article;
    }
    return null;
  }
  $('work-close').onclick = () => $('work-dialog').close();
  return {
    card,
    reset() {
      for (const url of urls) URL.revokeObjectURL(url);
      urls = [];
    },
  };
}
