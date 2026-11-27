// Reads the PNGs Chrome writes. Shared by the visual-qa capture (it cuts full shots into parts
// and measures blank regions) and fidelity.cjs (it compares a Refine base with the before shot).
// No other module is loaded, so requiring this runs nothing.
const fs = require('fs');
const zlib = require('zlib');

// The rows of an 8-bit, non-interlaced RGB or RGBA PNG (what Chrome writes), unfiltered; null
// for any other kind. Takes a file path or the PNG's bytes (fidelity.cjs passes either).
function decodePng(file) {
  const data = Buffer.isBuffer(file) ? file : fs.readFileSync(file);
  let pos = 8, width = 0, height = 0, depth = 0, ctype = 0, interlace = 0;
  const idat = [];
  while (pos < data.length) {
    const len = data.readUInt32BE(pos);
    const kind = data.toString('latin1', pos + 4, pos + 8);
    if (kind === 'IHDR') {
      width = data.readUInt32BE(pos + 8); height = data.readUInt32BE(pos + 12);
      depth = data[pos + 16]; ctype = data[pos + 17]; interlace = data[pos + 20];
    } else if (kind === 'IDAT') idat.push(data.subarray(pos + 8, pos + 8 + len));
    pos += 12 + len;
  }
  if (depth !== 8 || (ctype !== 2 && ctype !== 6) || interlace) return null;
  const bpp = ctype === 6 ? 4 : 3, stride = width * bpp;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const rows = [];
  let prev = Buffer.alloc(stride);
  for (let y = 0; y < height; y++) {
    const f = raw[y * (stride + 1)];
    const line = Buffer.from(raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1)));
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? line[i - bpp] : 0, b = prev[i], c = i >= bpp ? prev[i - bpp] : 0;
      if (f === 1) line[i] = (line[i] + a) & 255;
      else if (f === 2) line[i] = (line[i] + b) & 255;
      else if (f === 3) line[i] = (line[i] + ((a + b) >> 1)) & 255;
      else if (f === 4) {
        const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
        line[i] = (line[i] + (pa <= pb && pa <= pc ? a : pb <= pc ? b : c)) & 255;
      }
    }
    rows.push(line);
    prev = line;
  }
  return { width, height, bpp, ctype, rows };
}

module.exports = { decodePng };
