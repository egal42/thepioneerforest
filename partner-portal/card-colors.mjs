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
export function cardBackground(partnerBackground) {
  const light = luminance(partnerBackground);
  return light !== null && (1.05 / (light + 0.05)) >= 4.5
    ? partnerBackground : '#061b2b';
}
export function cardAccent(candidate, background) {
  const a = luminance(candidate), b = luminance(background);
  return a !== null && b !== null && (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) >= 3
    ? candidate : '#a8d8ff';
}
