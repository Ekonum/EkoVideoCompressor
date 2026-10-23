import { test } from 'node:test';
import assert from 'node:assert/strict';
import { combineGroups, fileKey, groupsFor, moveItem, splitGroup, uniqueFiles } from '../src/organizer.js';

const file = (name, type = 'audio/mp4') => new File(['audio'], name, { type, lastModified: 1700000000000 });
test('réunir une sélection non contiguë conserve tous les fichiers et leur ordre', () => {
  const files = ['partie1.m4a', 'autre.m4a', 'partie2.m4a', 'encore.m4a'].map((name) => file(name));
  const groups = groupsFor(files);
  const combined = combineGroups(groups, new Set([groups[0].id, groups[2].id]));
  assert.deepEqual(combined.map((group) => group.files.map((f) => f.name)), [
    ['partie1.m4a', 'partie2.m4a'], ['autre.m4a'], ['encore.m4a'],
  ]);
  assert.equal(new Set(combined.flatMap((group) => group.files)).size, files.length);
  assert.deepEqual(splitGroup(combined, combined[0].id).map((group) => group.files[0].name),
    ['partie1.m4a', 'partie2.m4a', 'autre.m4a', 'encore.m4a']);
});
test('le même dépôt ne duplique pas un fichier et ne modifie pas les listes source', () => {
  const original = file('partie.m4a');
  assert.equal(uniqueFiles([original, file('partie.m4a')]).length, 1);
  const groups = groupsFor([original, file('autre.m4a')]);
  const moved = moveItem(groups, 0, 1);
  assert.equal(moved[1].files[0], original);
  assert.equal(groups[0].files[0], original);
  assert.equal(moveItem(groups, 0, -1), groups);
});
test('les vidéos et enregistrements distants restent séparés', () => {
  const video = file('réunion.mp4', 'video/mp4');
  const groups = groupsFor([file('partie.m4a'), video]);
  assert.equal(combineGroups(groups, new Set(groups.map((g) => g.id))), groups);
});
test('changer l’ordre des morceaux invalide le contexte même à taille et date identiques', () => {
  const a = file('a.m4a'), b = file('b.m4a'), c = file('c.m4a');
  const first = file('réunion.m4a'), second = file('réunion.m4a');
  first.mergedParts = [a, b, c]; second.mergedParts = [a, c, b];
  assert.notEqual(fileKey(first), fileKey(second));
});
