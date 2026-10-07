import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { validateDraftProfile, validateSetup } from './contract.mjs';

export function signSync(secret, timestamp, method, path, body = '') {
  return createHmac('sha256', secret).update(`${timestamp}\n${method}\n${path}\n${body}`).digest('hex');
}

export function verifySync(request, body, secret, now = Date.now()) {
  if (!secret || secret.length < 32) return false;
  const timestamp = request.headers.get('x-tpf-timestamp');
  const signature = request.headers.get('x-tpf-signature');
  if (!/^\d{10,13}$/.test(timestamp || '') || !/^[a-f0-9]{64}$/.test(signature || '')) return false;
  const milliseconds = Number(timestamp) * 1000;
  if (Math.abs(now - milliseconds) > 300_000) return false;
  const url = new URL(request.url);
  const expected = signSync(secret, timestamp, request.method, url.pathname + url.search, body);
  return timingSafeEqual(Buffer.from(expected, 'hex'), Buffer.from(signature, 'hex'));
}

export function validatePublish(payload) {
  const profile = validateDraftProfile(payload?.profile);
  const setup = payload.setup == null ? null : validateSetup(payload.setup);
  if (setup && setup.partnerId !== profile.partnerId) throw new Error('Partner IDs differ');
  const revision = String(payload.revision || '');
  if (!/^[a-f0-9]{64}$/.test(revision)) throw new Error('Invalid revision');
  const logo = validateLogo(payload.logo);
  const connections = payload.connections == null ? [] : payload.connections;
  if (!Array.isArray(connections) || connections.length > 100 || (connections.length && !setup)) {
    throw new Error('Invalid request connections');
  }
  const poolIds = new Set(setup?.pools.map(pool => pool.id) || []);
  const seenRequests = new Set();
  const seenPools = new Set();
  for (const connection of connections) {
    if (!/^[a-f0-9-]{36}$/.test(connection?.requestId || '')
        || !/^[a-f0-9]{32}$/.test(connection?.offerId || '')
        || !String(connection?.choiceKey || '').trim()
        || !poolIds.has(connection?.poolId)
        || seenRequests.has(connection.requestId) || seenPools.has(connection.poolId)) {
      throw new Error('Invalid request connection');
    }
    seenRequests.add(connection.requestId);
    seenPools.add(connection.poolId);
  }
  return { profile, setup, revision, logo, connections };
}

function validateLogo(value) {
  if (value == null) return null;
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(value.contentType)
      || typeof value.data !== 'string' || value.data.length > 2_700_000
      || !/^[A-Za-z0-9+/]+={0,2}$/.test(value.data)) throw new Error('Invalid logo');
  const bytes = Buffer.from(value.data, 'base64');
  if (!bytes.length || bytes.length > 2_000_000 || bytes.toString('base64') !== value.data) throw new Error('Invalid logo');
  const png = bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'));
  const jpeg = bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  const webp = bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP';
  if (!(value.contentType === 'image/png' && png || value.contentType === 'image/jpeg' && jpeg
      || value.contentType === 'image/webp' && webp)) throw new Error('Logo format differs from the file');
  return { bytes, contentType: value.contentType,
    hash: createHash('sha256').update(bytes).digest('hex') };
}

export function validateOffer(payload) {
  const offer = payload?.offer;
  const requestId = String(payload?.requestId || '');
  const partnerId = String(payload?.partnerId || '');
  const revision = String(payload?.revision || '');
  if (!/^[a-f0-9]{32}$/.test(offer?.id || '') || !/^[a-f0-9-]{36}$/.test(requestId)
      || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(partnerId)
      || !/^[a-f0-9]{64}$/.test(revision)
      || offer.schema !== 'tpf_partner_offer_v1' || offer.status !== 'ready'
      || !Array.isArray(offer.choices) || !offer.choices.length || offer.choices.length > 8) {
    throw new Error('Invalid offer handoff');
  }
  const basis = offer.search?.basis;
  if (!['trees', 'co2'].includes(basis)) throw new Error('Invalid offer basis');
  const choices = offer.choices.map(choice => {
    const trees = Number(choice.trees);
    const co2Kg = Number(choice.co2_kg);
    const pricePi = Number(choice.partner_price_pi);
    if (!String(choice.key || '').trim() || String(choice.key).length > 150
        || !Number.isInteger(trees) || trees <= 0
        || !Number.isFinite(co2Kg) || co2Kg <= 0
        || !Number.isFinite(pricePi) || pricePi <= 0) throw new Error('Invalid offer choice');
    return { key: choice.key, project: String(choice.project || '').slice(0, 200),
      species: String(choice.species || '').slice(0, 200),
      commonName: String(choice.common_name || '').slice(0, 200),
      projectNote: String(choice.project_note || '').slice(0, 1000),
      trees, co2Kg, pricePi };
  });
  if (new Set(choices.map(c => c.key)).size !== choices.length) throw new Error('Duplicate choice');
  return { id: offer.id, requestId, partnerId, title: String(offer.name || '').slice(0, 200),
    basis, choices, revision };
}
