/** Accès à l'API. Une seule couche, pour que les composants ne
 *  connaissent ni les URLs ni la forme des erreurs. */

async function detail(response) {
  try {
    const body = await response.json();
    return body.detail || `Erreur ${response.status}`;
  } catch {
    return `Erreur ${response.status}`;
  }
}

async function call(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(await detail(response));
  return response.status === 204 ? null : response.json();
}

export const api = {
  listJobs: () => call('GET', '/api/jobs'),
  createJob: (payload) => call('POST', '/api/jobs', payload),
  job: (id) => call('GET', `/api/jobs/${id}`),
  detail: (id) => call('GET', `/api/jobs/${id}/detail`),
  finalize: (id) => call('POST', `/api/jobs/${id}/finalize`, {}),
  patch: (id, payload) => call('PATCH', `/api/jobs/${id}`, payload),
  replaceTerm: (id, old, next) =>
    call('POST', `/api/jobs/${id}/terms/replace`, { old, new: next }),
  resetChunk: (id, index) => call('POST', `/api/jobs/${id}/chunks/${index}/reset`, {}),
  search: (q) => call('GET', `/api/search?q=${encodeURIComponent(q)}`),
  vocabulary: (selected) =>
    call('GET', `/api/vocabulary?selected=${encodeURIComponent(selected.join(','))}`),
  settings: () => call('GET', '/api/settings'),
  odooMeetings: () => call('GET', '/api/odoo/meetings'),
  odooContext: (model, id) =>
    call('GET', `/api/odoo/context?model=${encodeURIComponent(model)}&record_id=${id}`),
};
