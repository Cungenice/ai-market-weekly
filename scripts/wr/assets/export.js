(() => {
  const button = document.querySelector('[data-export-highlights]');
  const section = document.getElementById('highlights');
  if (!button || !section) return;
  const status = document.querySelector('[data-export-status]');
  const width = 920, scale = 1.5, pad = 52, textWidth = width - 2 * pad;
  const fonts = {
    meta: '14px "Microsoft YaHei", "PingFang SC", sans-serif',
    title: '700 23px "Microsoft YaHei", "PingFang SC", sans-serif',
    label: '700 14px "Microsoft YaHei", "PingFang SC", sans-serif',
    body: '17px "Microsoft YaHei", "PingFang SC", sans-serif'
  };
  function wrap(ctx, text, font, maxWidth) {
    ctx.font = font;
    const lines = []; let line = '';
    for (const char of Array.from(text || '')) {
      if (line && ctx.measureText(line + char).width > maxWidth) {
        lines.push(line); line = char;
      } else line += char;
    }
    if (line) lines.push(line);
    return lines.length ? lines : [''];
  }
  function readField(article, selector) {
    const node = article.querySelector(selector);
    if (!node) return '';
    const copy = node.cloneNode(true);
    copy.querySelectorAll('b').forEach((label) => label.remove());
    return copy.textContent.replace(/\s+/g, ' ').trim();
  }
  function collectCards() {
    return Array.from(section.querySelectorAll('article.story')).map((article) => ({
      meta: article.querySelector('.meta')?.textContent.trim() || '',
      title: article.querySelector('h3')?.textContent.trim() || '',
      fields: [
        ['变了什么', readField(article, '.reported')],
        ['意味着什么', readField(article, '.analysis')],
        ['下周验证', readField(article, '.watch')]
      ].filter(([, text]) => text)
    }));
  }
  function prepare(card, ctx) {
    const meta = wrap(ctx, card.meta, fonts.meta, textWidth);
    const title = wrap(ctx, card.title, fonts.title, textWidth);
    const fields = card.fields.map(([label, text]) => ({
      label, lines: wrap(ctx, text, fonts.body, textWidth)
    }));
    const height = 18 + meta.length * 20 + 12 + title.length * 32
      + fields.reduce((sum, field) => sum + 8 + 20 + field.lines.length * 26 + 8, 0) + 18;
    return { meta, title, fields, height };
  }
  button.addEventListener('click', async () => {
    button.disabled = true; button.textContent = '正在生成…';
    try {
      const measure = document.createElement('canvas').getContext('2d');
      const cards = collectCards().map((card) => prepare(card, measure));
      const header = 170;
      const height = header + 28 + cards.reduce((sum, card) => sum + card.height + 16, 0) + 64;
      const canvas = document.createElement('canvas');
      canvas.width = width * scale; canvas.height = height * scale;
      const ctx = canvas.getContext('2d'); ctx.scale(scale, scale); ctx.textBaseline = 'top';
      ctx.fillStyle = '#f2f0ea'; ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = '#111820'; ctx.fillRect(0, 0, width, header);
      ctx.fillStyle = '#a52a35'; ctx.fillRect(0, 0, width, 6);
      ctx.fillStyle = '#e999a1'; ctx.font = '700 11px Arial';
      ctx.fillText('A/H EQUITY · AI & INNOVATION', pad, 26);
      ctx.fillStyle = '#fff'; ctx.font = '700 32px "Microsoft YaHei", sans-serif';
      ctx.fillText('本周重点', pad, 56);
      ctx.fillStyle = '#c4cbd0'; ctx.font = '14px "Microsoft YaHei", sans-serif';
      ctx.fillText('A 股 / 港股 · 人工智能与科技创新市场观察', pad, 112);
      let y = header + 28;
      for (const card of cards) {
        ctx.fillStyle = '#e9e6de'; ctx.fillRect(pad, y, width - 2 * pad, card.height);
        ctx.fillStyle = '#a52a35'; ctx.fillRect(pad, y, 4, card.height);
        let cy = y + 18;
        ctx.font = fonts.meta; ctx.fillStyle = '#687078';
        card.meta.forEach((line) => { ctx.fillText(line, pad + 22, cy); cy += 20; });
        cy += 12;
        ctx.font = fonts.title; ctx.fillStyle = '#202326';
        card.title.forEach((line) => { ctx.fillText(line, pad + 22, cy); cy += 32; });
        for (const field of card.fields) {
          cy += 8; ctx.font = fonts.label; ctx.fillStyle = '#a52a35';
          ctx.fillText(field.label, pad + 22, cy); cy += 20;
          ctx.font = fonts.body; ctx.fillStyle = '#202326';
          field.lines.forEach((line) => { ctx.fillText(line, pad + 22, cy); cy += 26; });
          cy += 8;
        }
        y += card.height + 16;
      }
      ctx.fillStyle = '#687078'; ctx.font = '13px "Microsoft YaHei", sans-serif';
      ctx.fillText('来源和完整内容请访问周报网页 · 不构成投资建议', pad, y + 12);
      const blob = await new Promise((resolve, reject) =>
        canvas.toBlob((value) => value ? resolve(value) : reject(new Error('PNG 导出失败')), 'image/png'));
      const url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href = url; link.download = 'A股港股AI市场周报_本周重点.png';
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      if (status) status.textContent = 'PNG 已下载。';
    } catch (error) {
      console.error(error);
      if (status) status.textContent = '导出失败，请刷新页面后重试。';
    } finally {
      button.disabled = false; button.textContent = '下载本周重点长图';
    }
  });
})();
