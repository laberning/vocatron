// Writes the frames of a .cdg file as raw RGBA (300 x 216 x 4 bytes each) to standard output.
//
// Usage: node cdg_frames.mjs <cdgraphics.js> <file.cdg> <time in seconds>...
//
// The package cdgraphics is imported as it is (ADR-0025). It draws into an ImageData, a browser
// class that Node does not have, so this script defines the plain object it needs.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

globalThis.ImageData = class ImageData {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.data = new Uint8ClampedArray(width * height * 4);
  }
};

const [library, file, ...times] = process.argv.slice(2);
const { default: CDGraphics } = await import(pathToFileURL(library).href);
const bytes = readFileSync(file);
const player = new CDGraphics(
  bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
);
for (const time of times) {
  const frame = player.render(Number(time));
  process.stdout.write(Buffer.from(frame.imageData.data.buffer.slice(0)));
}
