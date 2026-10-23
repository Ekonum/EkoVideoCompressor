import {
  Input, Output, Conversion, ALL_FORMATS, BlobSource, StreamTarget,
  Mp4OutputFormat, EncodedAudioPacketSource, EncodedPacketSink, Quality, AudioSample,
} from 'mediabunny';

// Certains HE-AAC se déclarent mono mais se décodent en stéréo.
function mono(sample) {
  if (sample.numberOfChannels === 1) return sample;
  const frames = sample.numberOfFrames;
  if (!frames) return null;
  const data = new Float32Array(frames);
  const channel = new Float32Array(frames);
  for (let c = 0; c < sample.numberOfChannels; c++) {
    sample.copyTo(channel, { planeIndex: c, format: 'f32-planar' });
    for (let i = 0; i < frames; i++) data[i] += channel[i] / sample.numberOfChannels;
  }
  return new AudioSample({ data, format: 'f32-planar', numberOfChannels: 1,
    sampleRate: sample.sampleRate, timestamp: sample.timestamp });
}

self.onmessage = async ({ data: { files, handle, temporaryName } }) => {
  const root = await navigator.storage.getDirectory();
  let output;
  let input;
  try {
    output = new Output({ format: new Mp4OutputFormat(), target: new StreamTarget(await handle.createWritable()) });
    const source = new EncodedAudioPacketSource('aac');
    output.addAudioTrack(source);
    await output.start();
    let offset = 0;
    let firstDuration = 0;
    const parts = [];
    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      const temporary = await root.getFileHandle(temporaryName, { create: true });
      input = new Input({ formats: ALL_FORMATS, source: new BlobSource(file) });
      const audio = await input.getPrimaryAudioTrack();
      if (!audio || await input.getPrimaryVideoTrack()) throw new Error('Choisis uniquement des fichiers audio à réunir.');
      const duration = await input.computeDuration();
      if (!Number.isFinite(duration) || duration <= 0) throw new Error(`Durée illisible pour « ${file.name} ».`);
      if (index === 0) firstDuration = duration;
      // Un seul réencodage par morceau, puis copie des paquets AAC dans
      // une piste unique. Les fichiers temporaires restent petits et la
      // mémoire ne dépend pas de la durée totale de la réunion.
      const conversion = await Conversion.init({ input,
        output: new Output({ format: new Mp4OutputFormat(), target: new StreamTarget(await temporary.createWritable()) }),
        video: { discard: true },
        audio: { codec: 'aac', sampleRate: 48000, numberOfChannels: 1,
          quality: new Quality({ bitrate: 64000 }), process: mono, processedNumberOfChannels: 1 },
      });
      if (!conversion.isValid) throw new Error(`Impossible de lire « ${file.name} ».`);
      conversion.onProgress = (ratio) => self.postMessage({ kind: 'progress', index, total: files.length,
        ratio: (index + ratio) / files.length });
      await conversion.execute();
      input.dispose();
      input = new Input({ formats: ALL_FORMATS, source: new BlobSource(await temporary.getFile()) });
      const track = await input.getPrimaryAudioTrack();
      const decoderConfig = await track.getDecoderConfig();
      const sink = new EncodedPacketSink(track);
      let start = null;
      let end = offset;
      for await (const packet of sink.packets()) {
        start ??= packet.timestamp;
        const timestamp = offset + packet.timestamp - start;
        await source.add(packet.clone({ timestamp }), { decoderConfig });
        end = Math.max(end, timestamp + packet.duration);
      }
      if (start === null) throw new Error(`« ${file.name} » ne contient aucun son lisible.`);
      parts.push({ name: file.name, start: offset, end });
      offset = end;
      input.dispose();
      input = null;
      await root.removeEntry(temporaryName);
    }
    source.close();
    await output.finalize();
    self.postMessage({ kind: 'done', duration: offset, firstDuration, parts });
  } catch (error) {
    await output?.cancel().catch(() => {});
    self.postMessage({ kind: 'error', message: error?.message || 'L’assemblage audio a échoué.' });
  } finally {
    input?.dispose();
    await root.removeEntry(temporaryName).catch(() => {});
  }
};
