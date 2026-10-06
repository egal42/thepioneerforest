/* Supporting decorative hue: same HLS rotation as the sandbox supporting_accent. */
function applyPartnerTheme(colors, partnerId) {
  for (const [key,value] of Object.entries(colors || {})) {
    const mapped = key === 'background' ? 'bg' : key;
    if (['bg','panel','accent','text','secondary'].includes(mapped) && /^#[a-fA-F0-9]{6}$/.test(value))
      document.documentElement.style.setProperty('--'+mapped,value);
  }
  const accent = colors?.accent || '#43DCFF';
  let spark = accent;
  if (colors?.colorful ?? partnerId === 'omc') {
    const [r,g,b]=[1,3,5].map(i=>parseInt(accent.slice(i,i+2),16)/255);
    const max=Math.max(r,g,b),min=Math.min(r,g,b),delta=max-min;
    let hue=delta===0 ? 0 : max===r ? ((g-b)/delta)%6 : max===g ? (b-r)/delta+2 : (r-g)/delta+4;
    hue=((hue/6+0.54)%1+1)%1;
    const l=.68,s=.65,c=(1-Math.abs(2*l-1))*s,x=c*(1-Math.abs((hue*6)%2-1)),m=l-c/2;
    const sector=Math.floor(hue*6),channels=[[c,x,0],[x,c,0],[0,c,x],[0,x,c],[x,0,c],[c,0,x]][sector];
    spark='#'+channels.map(v=>Math.round((v+m)*255).toString(16).padStart(2,'0')).join('').toUpperCase();
  }
  document.documentElement.style.setProperty('--spark',spark);
}
