import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import { clipAudioParts } from '../audio-parts.js';
import { horodatage } from '../format.js';

/** <ekn-audio> d'ekonum-ui, monté hors de React.
 *
 *  Le composant dessine ses contrôles à côté de la <video> et, pour
 *  rogner, la déplace dans son cadre : React ne doit pas gérer ses
 *  enfants. On l'assemble donc à la main dans un hôte vide, et on le
 *  recrée quand la source change — `start` et `end` ne sont lus qu'au
 *  chargement.
 */
export const EknAudio = forwardRef(function EknAudio(
  { src, trim = false, start, end, duration, label, autoPlay = false, onTrim, onTime, onUnreadable, className = '', inert, parts },
  ref,
) {
  const hote = useRef(null);
  const lecteur = useRef(null);
  const rappels = useRef({});
  rappels.current = { onTrim, onTime, onUnreadable };

  useImperativeHandle(ref, () => ({
    seek: (seconds, play = true) => lecteur.current?.seek(seconds, play),
  }), []);

  useEffect(() => {
    if (!src) return undefined;
    const el = document.createElement('ekn-audio');
    if (trim) el.setAttribute('trim', '');
    if (label) el.setAttribute('label', label);
    if (start != null) el.setAttribute('start', String(start));
    if (end != null) el.setAttribute('end', String(end));
    // Rogner reste possible quand le navigateur ne lit pas le média : la
    // durée sondée par Mediabunny tient lieu de la sienne.
    if (duration) el.setAttribute('duration', String(duration));
    const media = document.createElement('video');
    media.preload = 'metadata';
    media.playsInline = true;
    media.controls = true; // sans le script, le lecteur du navigateur reste
    media.autoplay = autoPlay;
    media.src = src;
    el.append(media);
    el.addEventListener('ekn-trim', (e) => rappels.current.onTrim?.(e.detail));
    media.addEventListener('timeupdate', () => rappels.current.onTime?.(media.currentTime));
    media.addEventListener('error', () => rappels.current.onUnreadable?.());
    hote.current.append(el);
    lecteur.current = el;
    return () => {
      // Libère la lecture et la connexion : retirer l'élément ne suffit pas.
      media.pause();
      media.removeAttribute('src');
      media.load();
      el.remove();
      lecteur.current = null;
    };
    // start / end ne valent qu'au chargement : les suivre recréerait le
    // lecteur à chaque poignée déplacée.
  }, [src, trim, duration, label, autoPlay]);

  // L’adaptateur ajoute des repères sans modifier le composant partagé.
  // Les contrôles et le rognage restent ceux d’ekonum-ui.
  useEffect(() => {
    const el = lecteur.current;
    const chapters = clipAudioParts(parts);
    if (!el || chapters.length < 2) return undefined;
    const media = el.querySelector('video');
    const range = el.querySelector('.ekn-audio__seek');
    const timeline = el.querySelector('.ekn-audio__timeline');
    let wrapper;
    if (!timeline && range) {
      wrapper = document.createElement('span');
      wrapper.className = 'audio-parts-seek';
      range.before(wrapper); wrapper.append(range);
    }
    const host = timeline || wrapper;
    if (!host) return undefined;
    const markers = document.createElement('span');
    markers.className = 'audio-part-markers'; markers.setAttribute('aria-hidden', 'true');
    host.append(markers);
    const paint = () => {
      const scale = Number(el.querySelector('input[type=range]')?.max) || Math.floor(duration || media.duration);
      markers.replaceChildren();
      if (!(scale > 0)) return;
      for (const part of chapters.slice(1)) {
        if (part.start >= scale) continue;
        const marker = document.createElement('span'); marker.className = 'audio-part-marker';
        const ratio = part.start / scale;
        marker.style.left = `calc(8px + (100% - 16px) * ${ratio})`;
        markers.append(marker);
      }
    };
    paint(); media.addEventListener('loadedmetadata', paint); media.addEventListener('durationchange', paint);
    return () => {
      media.removeEventListener('loadedmetadata', paint); media.removeEventListener('durationchange', paint);
      markers.remove();
      if (wrapper) { wrapper.before(range); wrapper.remove(); }
    };
  }, [parts, duration, src, trim, label, autoPlay]);

  const chapters = clipAudioParts(parts);
  return <div className={className} inert={inert}>
    <div ref={hote} />
    {chapters.length > 1 && <nav className="audio-part-links" aria-label="Morceaux de l’enregistrement">
      {chapters.map((part, index) => <button key={`${part.start}-${index}`} type="button"
        className="audio-part-link" title={part.name}
        aria-label={`Aller au morceau ${index + 1} : ${part.name}, à ${horodatage(part.start)}`}
        onClick={() => lecteur.current?.seek(part.start, false)}>
        <span aria-hidden="true" className="text-ekn-text-muted">{index + 1}</span>
        <span className="truncate">{part.name}</span>
        <time className="text-ekn-text-muted">{horodatage(part.start)}</time>
      </button>)}
    </nav>}
  </div>;
});

/** Le lecteur de transcript, pour l'audio comme pour la vidéo.
 *
 *  `seek(seconds)` est exposé pour que la transcription puisse y mener ;
 *  `onTime` lui renvoie l'instant écouté. L'image n'apparaît que s'il y
 *  en a une.
 */
export const MediaPlayer = forwardRef(function MediaPlayer({ src, autoPlay = false, onTime, parts, duration }, ref) {
  return <EknAudio ref={ref} src={src} autoPlay={autoPlay} onTime={onTime} parts={parts} duration={duration} className="mt-3" />;
});
