function rgb(hex) {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex || '')) return null;
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255);
}
function luminance(hex) {
  const values = rgb(hex);
  if (!values) return null;
  const linear = values.map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}
function contrast(a, b) {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
export function cardBackground(partnerBackground) {
  return rgb(partnerBackground) ? partnerBackground : '#061b2b';
}
export function cardText(background) {
  const light = luminance(cardBackground(background));
  return contrast(0, light) >= contrast(1, light) ? '#000000' : '#ffffff';
}
export function cardAccent(candidate, background) {
  const a = luminance(candidate), b = luminance(cardBackground(background));
  return a !== null && contrast(a, b) >= 4.5 ? candidate : cardText(background);
}
export function cardOverlay(background, opacity) {
  const hex = cardBackground(background);
  const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${channels.join(',')},${opacity})`;
}
