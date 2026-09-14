/**
 * Fil principal : sonde le fichier, crée le job, délègue l'encodage au
 * worker, et suit l'avancement.
 *
 * Le plan de découpage vient du serveur et n'est jamais recalculé ici —
 * une seule source de vérité, côté `plan_audio_chunks`.
 */
import { Input, ALL_FORMATS, BlobSource } from './vendor/mediabunny.mjs';

const $ = (id) => document.getElementById(id);
const mb = (bytes) => (bytes / 1048576).toFixed(1) + ' Mo';
const hms = (s) => {
  const t = Math.round(s);
  return `${Math.floor(t / 3600)}:${String(Math.floor((t % 3600) / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
};
const list = (value) =>
  value.split(',').map((part) => part.trim()).filter(Boolean);

let file = null;
let duration = 0;

// -- barrière de capacités ------------------------------------------------
// Mieux vaut le dire franchement à l'ouverture que d'échouer à mi-course.
{
  const missing = [];
  if (!window.isSecureContext) missing.push('un contexte sécurisé (HTTPS)');
  if (typeof AudioEncoder === 'undefined') missing.push('WebCodecs (AudioEncoder)');
  if (!window.Worker) missing.push('les Web Workers');
  if (missing.length) {
    $('gate').hidden = false;
    $('gateDetail').textContent =
      'Il manque à ce navigateur : ' + missing.join(', ') +
      '. Chrome, Edge ou Safari 26 et plus font l’affaire.';
  }
}

// -- fichier --------------------------------------------------------------

$('file').addEventListener('change', async (event) => {
  file = event.target.files[0] || null;
  $('go').disabled = true;
  if (!file) { $('fileInfo').textContent = ''; return; }

  $('fileInfo').textContent = 'Lecture des métadonnées…';
  try {
    const input = new Input({ formats: ALL_FORMATS, source: new BlobSource(file) });
    duration = await input.computeDuration();
    $('fileInfo').textContent = `${mb(file.size)} · ${hms(duration)}`;
    $('go').disabled = false;
  } catch (error) {
    $('fileInfo').innerHTML = `<span class="ko">Fichier illisible : ${error.message}</span>`;
  }
});

// Entrée de rodage : « ?source=/chemin » charge un fichier servi par le
// serveur au lieu de passer par le sélecteur, ce qui rend la chaîne
// complète vérifiable sans intervention humaine. Même origine, derrière
// Access comme le reste — rien n'est contourné.
{
  const source = new URLSearchParams(location.search).get('source');
  if (source) {
    (async () => {
      $('fileInfo').textContent = `Chargement de ${source}…`;
      const blob = await (await fetch(source)).blob();
      file = new File([blob], source.split('/').pop(), { type: blob.type });
      const input = new Input({ formats: ALL_FORMATS, source: new BlobSource(file) });
      duration = await input.computeDuration();
      $('fileInfo').textContent = `${mb(file.size)} · ${hms(duration)} (rodage)`;
      $('go').disabled = false;
    })().catch((error) => {
      $('fileInfo').innerHTML = `<span class="ko">${error.message}</span>`;
    });
  }
}

// -- lancement ------------------------------------------------------------

$('go').addEventListener('click', async () => {
  $('go').disabled = true;
  $('progressCard').hidden = false;
  $('resultCard').hidden = true;
  $('phase').textContent = 'Création du traitement…';

  let job;
  try {
    job = await post('/api/jobs', {
      filename: file.name,
      duration_seconds: duration,
      model: 'gemini-3.8-flash',
      language: 'fr',
      context: {
        client_company: $('client').value.trim(),
        expected_speaker_names: list($('speakers').value),
        glossary_terms: list($('glossary').value),
      },
    });
  } catch (error) {
    // Le garde-fou budget répond ici, avant le premier octet uploadé.
    $('phase').innerHTML = `<span class="ko">${error.message}</span>`;
    $('go').disabled = false;
    return;
  }

  $('estimate').textContent = `Coût estimé : ${job.estimated_cost_usd.toFixed(2)} $US`;
  renderRows(job.chunks);

  const state = await get(`/api/jobs/${job.job_id}`);
  const worker = new Worker('./media-worker.js', { type: 'module' });
  worker.postMessage({
    file,
    jobId: job.job_id,
    chunks: job.chunks,
    audio: job.audio,
    pending: state.missing_chunks,   // reprise : on ne réencode que ce qui manque
  });

  worker.onmessage = (event) => onWorkerMessage(event.data, job);
  poll(job);
});

// -- rendu ----------------------------------------------------------------

const rows = new Map();

function renderRows(chunks) {
  $('rows').innerHTML = '';
  rows.clear();
  for (const chunk of chunks) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${chunk.index + 1}</td><td>${hms(chunk.start)}</td>` +
                   `<td class="state">en attente</td><td class="num size"></td>`;
    $('rows').append(tr);
    rows.set(chunk.index, tr);
  }
}

function setState(index, text, cls = '') {
  const cell = rows.get(index)?.querySelector('.state');
  if (cell) { cell.textContent = text; cell.className = 'state ' + cls; }
}

function onWorkerMessage(message, job) {
  switch (message.kind) {
    case 'encoding':
      setState(message.index, `encodage ${Math.round(message.ratio * 100)} %`);
      break;
    case 'encoded':
      rows.get(message.index).querySelector('.size').textContent = mb(message.bytes);
      setState(message.index, 'envoi…');
      break;
    case 'uploaded':
      setState(message.index, 'transcription…');
      break;
    case 'done':
      $('phase').textContent = 'Fenêtres envoyées, transcription en cours…';
      break;
    case 'error':
      $('phase').innerHTML = `<span class="ko">${message.message}</span>`;
      break;
  }
}

// -- suivi ----------------------------------------------------------------

async function poll(job) {
  // Le serveur répond 202 à l'envoi : l'avancement se lit ici, pas dans
  // la réponse de l'upload.
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 3000));
    const state = await get(`/api/jobs/${job.job_id}`);

    let done = 0;
    for (const chunk of state.chunks) {
      if (chunk.status === 'termine') { setState(chunk.index, 'terminée', 'ok'); done += 1; }
      else if (chunk.status === 'erreur') setState(chunk.index, chunk.error || 'erreur', 'ko');
    }
    $('overall').value = done / state.chunks.length;

    if (state.status === 'erreur') {
      $('phase').innerHTML = `<span class="ko">${state.error}</span>`;
      $('go').disabled = false;
      return;
    }
    if (state.status === 'a_finaliser') {
      $('phase').textContent = 'Fusion des fenêtres…';
      const final = await post(`/api/jobs/${job.job_id}/finalize`, {});
      show(final);
      return;
    }
  }
}

function show(final) {
  $('resultCard').hidden = false;
  $('resultTitle').textContent = final.title || 'Transcription';
  $('resultMeta').textContent =
    `${final.transcript.split('\n').length} lignes · ` +
    `coût réel ${final.cost_usd.toFixed(2)} $US · ` +
    `termes relevés : ${final.technical_terms.join(', ') || '—'}`;
  $('transcript').textContent = final.transcript;
  $('phase').innerHTML = '<span class="ok">Terminé.</span>';
  $('go').disabled = false;
}

// -- HTTP -----------------------------------------------------------------

async function get(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

async function post(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await detail(response));
  return response.json();
}

async function detail(response) {
  try {
    const body = await response.json();
    return body.detail || `${response.status}`;
  } catch {
    return `${response.status}`;
  }
}
