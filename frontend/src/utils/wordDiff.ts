export type WordDiffItem = { type: 'same' | 'removed' | 'added'; text: string };

/**
 * 단어 수준 diff: 원본과 수정본 비교하여 변경된 단어만 표시
 */
export function getWordDiff(original: string, edited: string): WordDiffItem[] {
  if (original === edited) return [];

  const origWords = original.split(/(\s+)/);
  const editWords = edited.split(/(\s+)/);

  const result: WordDiffItem[] = [];
  let i = 0;
  let j = 0;

  while (i < origWords.length && j < editWords.length) {
    if (origWords[i] === editWords[j]) {
      result.push({ type: 'same', text: origWords[i] ?? '' });
      i++;
      j++;
    } else {
      let foundOrig = -1;
      let foundEdit = -1;
      for (let k = j + 1; k < Math.min(j + 5, editWords.length); k++) {
        if (origWords[i] === editWords[k]) { foundEdit = k; break; }
      }
      for (let k = i + 1; k < Math.min(i + 5, origWords.length); k++) {
        if (origWords[k] === editWords[j]) { foundOrig = k; break; }
      }

      if (foundEdit >= 0 && (foundOrig < 0 || foundEdit - j <= foundOrig - i)) {
        for (let k = j; k < foundEdit; k++) {
          result.push({ type: 'added', text: editWords[k] ?? '' });
        }
        j = foundEdit;
      } else if (foundOrig >= 0) {
        for (let k = i; k < foundOrig; k++) {
          result.push({ type: 'removed', text: origWords[k] ?? '' });
        }
        i = foundOrig;
      } else {
        result.push({ type: 'removed', text: origWords[i] ?? '' });
        result.push({ type: 'added', text: editWords[j] ?? '' });
        i++;
        j++;
      }
    }
  }
  while (i < origWords.length) {
    result.push({ type: 'removed', text: origWords[i++] ?? '' });
  }
  while (j < editWords.length) {
    result.push({ type: 'added', text: editWords[j++] ?? '' });
  }
  return result;
}
