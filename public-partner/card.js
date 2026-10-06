import { cardArtworkSvg } from '/partner-portal/card-art.mjs';
import { cardAccent, cardBackground } from '/partner-portal/card-colors.mjs';

function fitted(ctx, value, maxWidth, start, min) {
  let size = start;
  while (size > min) {
    ctx.font = `900 ${size}px Arial, sans-serif`;
    if (ctx.measureText(value).width <= maxWidth) break;
    size -= 2;
  }
  return size;
}

export async function drawShareCard(canvas, profile, record, template) {
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.height = 1080;
  const bg = cardBackground(profile.colors?.background);
  const accent = cardAccent(profile.colors?.accent, bg);
  const secondary = cardAccent(profile.colors?.secondary, bg);
  ctx.fillStyle = bg; ctx.fillRect(0, 0, 1080, 1080);
  const svgUrl = URL.createObjectURL(new Blob([cardArtworkSvg(template, accent, secondary)], { type: 'image/svg+xml' }));
  try {
    const image = new Image(); image.src = svgUrl;
    await image.decode(); ctx.drawImage(image, 0, 0, 1080, 1080);
  } finally { URL.revokeObjectURL(svgUrl); }
  const scrim = ctx.createRadialGradient(540, 520, 30, 540, 520, 420);
  scrim.addColorStop(0, 'rgba(4,21,36,.98)');
  scrim.addColorStop(.65, 'rgba(4,21,36,.91)');
  scrim.addColorStop(1, 'rgba(4,21,36,0)');
  ctx.fillStyle = scrim; ctx.fillRect(100, 180, 880, 740);
  ctx.textAlign = 'center';
  ctx.fillStyle = '#f5fbf4'; ctx.font = '900 25px Arial, sans-serif';
  ctx.fillText('COMMUNITY REWARD', 540, 350);
  const amount = String(record.units);
  ctx.font = `900 ${fitted(ctx, amount, 650, 120, 62)}px Arial, sans-serif`;
  ctx.shadowColor = accent; ctx.shadowBlur = 22; ctx.fillText(amount, 540, 465); ctx.shadowBlur = 0;
  ctx.fillStyle = accent; ctx.font = '900 48px Arial, sans-serif';
  ctx.fillText(record.basis === 'trees' ? (Number(amount) === 1 ? 'TREE' : 'TREES') : 'KG CO₂', 540, 526);
  ctx.fillStyle = '#f5fbf4'; ctx.font = '30px Arial, sans-serif'; ctx.fillText('shared with', 540, 586);
  const pioneer = String(record.pioneer_name);
  ctx.font = `900 ${fitted(ctx, pioneer, 760, 52, 30)}px Arial, sans-serif`;
  ctx.fillText(pioneer, 540, 646);
  if (record.reason) {
    ctx.font = `25px Arial, sans-serif`;
    ctx.fillText(('For: ' + record.reason).slice(0, 55), 540, 718);
  }
  ctx.strokeStyle = accent; ctx.lineWidth = 2; ctx.strokeRect(190, 790, 700, 68);
  ctx.font = `700 ${fitted(ctx, 'Pool: ' + record.pool_name, 650, 25, 18)}px Arial, sans-serif`;
  ctx.fillText('Pool: ' + record.pool_name, 540, 833);
  const brand = `${profile.name} × The Pioneer Forest`;
  ctx.font = `700 ${fitted(ctx, brand, 900, 27, 16)}px Arial, sans-serif`;
  ctx.fillText(brand, 540, 1000);
}
