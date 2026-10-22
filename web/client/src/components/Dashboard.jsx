import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { Erreur } from './Communs.jsx';

/** Le tableau de bord de « Mon compte » : combien de réunions, et ce
 *  qu'elles ont coûté, sur une période.
 *
 *  Le graphique suit ekonum-ui : l'application dessine son SVG à la
 *  largeur de son conteneur (jamais réduit, ses libellés de 12 px
 *  deviendraient illisibles sur un téléphone), le paquet en donne les
 *  couleurs. Les réunions sont la première série, le coût la deuxième.
 */
const PERIODS = { 30: '30 jours', 90: '90 jours', 365: '1 an', all: 'Depuis le début' };
const HEIGHT = 200;
const PAD = { top: 12, right: 44, bottom: 24, left: 32 };

const euros = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR' });
const dollars = new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' });
const nombre = new Intl.NumberFormat('fr-FR');
const court = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'short' });
const mois = new Intl.DateTimeFormat('fr-FR', { month: 'short', year: 'numeric' });
const long = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' });

const asDate = (iso) => new Date(`${iso}T12:00:00`);

function bucketLabel(iso, bucket) {
  if (bucket === 'month') return mois.format(asDate(iso));
  if (bucket === 'week') return `semaine du ${court.format(asDate(iso))}`;
  return long.format(asDate(iso));
}

const tickLabel = (iso, bucket) =>
  bucket === 'month' ? mois.format(asDate(iso)) : court.format(asDate(iso));

/** Un maximum rond pour l'axe : 1, 2, 5, 10, 20… au-dessus de la valeur. */
function niceMax(value) {
  if (value <= 0) return 1;
  const pow = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 5, 10].find((s) => s * pow >= value);
  return step * pow;
}

export function Dashboard() {
  const [period, setPeriod] = useState('30');
  const [stats, setStats] = useState(null);
  const [erreur, setErreur] = useState('');
  const [withCost, setWithCost] = useState(false);

  useEffect(() => {
    let current = true;
    api.myStats(period)
      .then((s) => { if (current) { setStats(s); setErreur(''); } })
      .catch((e) => { if (current) setErreur(e.message); });
    return () => { current = false; };
  }, [period]);

  const inEuros = stats?.totals.cost_eur != null;
  const cost = (b) => (inEuros ? b.cost_eur : b.cost_usd);
  const money = (v) => (inEuros ? euros : dollars).format(v);
  const unit = { day: 'jour', week: 'semaine', month: 'mois' }[stats?.bucket] || 'jour';
  const total = stats?.totals.meetings ?? 0;

  return (
    <div className="verre mt-8 rounded-xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="titre text-[1.0625rem] font-medium">Activité</h2>
        <fieldset className="ekn-chips">
          <legend>Période</legend>
          {Object.entries(PERIODS).map(([key, label]) => (
            <label key={key}>
              <input
                type="radio"
                name="periode"
                value={key}
                checked={period === key}
                onChange={() => setPeriod(key)}
              />
              {label}
            </label>
          ))}
        </fieldset>
      </div>

      <Erreur>{erreur}</Erreur>

      {stats ? (
        <>
          <div className="ekn-metrics ekn-metrics--inline mt-4">
            <div className="ekn-metric">
              <span className="ekn-metric__label">Réunions</span>
              <span className="ekn-metric__value">{nombre.format(total)}</span>
              <span className="ekn-metric__hint">
                depuis le {long.format(asDate(stats.from))}
              </span>
            </div>
            <div className="ekn-metric">
              <span className="ekn-metric__label">Coût</span>
              <span className="ekn-metric__value">{money(cost(stats.totals))}</span>
              <span className="ekn-metric__hint">
                {stats.rate
                  ? `1 € = ${nombre.format(stats.rate.usd_per_eur)} $ (BCE, ${court.format(asDate(stats.rate.published))})`
                  : 'en dollars : cours de la BCE indisponible'}
              </span>
            </div>
            <div className="ekn-metric">
              <span className="ekn-metric__label">Par réunion</span>
              <span className="ekn-metric__value">
                {total ? money(cost(stats.totals) / total) : '—'}
              </span>
              <span className="ekn-metric__hint">en moyenne</span>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <ul className="ekn-legend">
              <li className="ekn-series-1"><span className="ekn-swatch" />Réunions par {unit}</li>
              {withCost ? (
                <li className="ekn-series-2"><span className="ekn-swatch" />Coût ({inEuros ? '€' : '$'})</li>
              ) : null}
            </ul>
            <label className="ekn-option">
              <input
                type="checkbox"
                role="switch"
                className="ekn-switch"
                checked={withCost}
                onChange={(e) => setWithCost(e.target.checked)}
              />
              Superposer le coût
            </label>
          </div>

          <Chart
            stats={stats}
            cost={cost}
            money={money}
            withCost={withCost}
          />
        </>
      ) : null}
    </div>
  );
}

function Chart({ stats, cost, money, withCost }) {
  const box = useRef(null);
  const [width, setWidth] = useState(0);
  const [hover, setHover] = useState(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const series = stats.series;
  const total = stats.totals.meetings;
  const maxMeetings = niceMax(Math.max(0, ...series.map((b) => b.meetings)));
  const maxCost = niceMax(Math.max(0, ...series.map(cost)));
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const step = series.length ? plotW / series.length : 0;
  const barW = Math.max(1, step * 0.7);
  const x = (i) => PAD.left + i * step;
  const yMeetings = (v) => PAD.top + plotH - (v / maxMeetings) * plotH;
  const yCost = (v) => PAD.top + plotH - (v / maxCost) * plotH;
  // Six libellés au plus sur l'axe : au-delà, ils se chevauchent sur un
  // téléphone.
  const every = Math.max(1, Math.ceil(series.length / 6));
  // On compte des réunions : pas de graduation à « 2,5 ».
  const ticks = [0, 0.5, 1].filter((f) => Number.isInteger(maxMeetings * f));

  const resume =
    `${total} réunion${total > 1 ? 's' : ''} du ${long.format(asDate(stats.from))} ` +
    `au ${long.format(asDate(stats.to))}, pour ${money(cost(stats.totals))}.`;

  return (
    <div ref={box} className="relative mt-3">
      {width ? (
        <svg className="ekn-chart" height={HEIGHT} role="img" aria-label={resume}>
          <g className="ekn-chart__grid">
            {ticks.map((f) => (
              <line key={f} x1={PAD.left} x2={PAD.left + plotW} y1={yMeetings(maxMeetings * f)} y2={yMeetings(maxMeetings * f)} />
            ))}
          </g>
          <g className="ekn-chart__axis">
            {ticks.map((f) => (
              <text key={f} x={PAD.left - 6} y={yMeetings(maxMeetings * f) + 4} textAnchor="end">
                {nombre.format(maxMeetings * f)}
              </text>
            ))}
            {withCost ? [0.5, 1].map((f) => (
              <text key={`c${f}`} x={PAD.left + plotW + 6} y={yCost(maxCost * f) + 4} textAnchor="start">
                {money(maxCost * f).replace(/,00\s/, ' ')}
              </text>
            )) : null}
            {series.map((b, i) => (i % every === 0 ? (
              <text key={b.start} x={x(i) + step / 2} y={HEIGHT - 6} textAnchor="middle">
                {tickLabel(b.start, stats.bucket)}
              </text>
            ) : null))}
          </g>
          <g className="ekn-series-1">
            {series.map((b, i) => (b.meetings ? (
              <rect
                key={b.start}
                className="ekn-chart__bar"
                x={x(i) + (step - barW) / 2}
                width={barW}
                y={yMeetings(b.meetings)}
                height={PAD.top + plotH - yMeetings(b.meetings)}
              />
            ) : null))}
          </g>
          {withCost ? (
            <g className="ekn-series-2">
              <polyline
                className="ekn-chart__line"
                points={series.map((b, i) => `${x(i) + step / 2},${yCost(cost(b))}`).join(' ')}
              />
            </g>
          ) : null}
          <g>
            {series.map((b, i) => (
              <rect
                key={b.start}
                className="ekn-chart__hit"
                x={x(i)}
                width={step}
                y={PAD.top}
                height={plotH}
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            ))}
          </g>
        </svg>
      ) : null}
      {hover != null && series[hover] ? (
        <div
          className="ekn-tooltip"
          style={{
            left: Math.min(Math.max(0, x(hover) + step / 2 - 96), Math.max(0, width - 192)),
            top: 0,
          }}
        >
          <strong>{bucketLabel(series[hover].start, stats.bucket)}</strong>
          <ul className="ekn-legend mt-1">
            <li className="ekn-series-1">
              <span className="ekn-swatch" />
              {series[hover].meetings} réunion{series[hover].meetings > 1 ? 's' : ''}
            </li>
            <li className="ekn-series-2">
              <span className="ekn-swatch" />
              {money(cost(series[hover]))}
            </li>
          </ul>
        </div>
      ) : null}
    </div>
  );
}
