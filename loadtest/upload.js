import http from "k6/http";
import { check, sleep } from "k6";
import { randomBytes } from "k6/crypto";
import { open as openFile, SeekMode } from "k6/experimental/fs";
import { Counter } from "k6/metrics";

const endpoint = __ENV.IMMICH_URL || "http://host.docker.internal:2283";
const apiKey = __ENV.IMMICH_API_KEY;
const photoRatio = Number(__ENV.PHOTO_RATIO || "0.5");
const vus = Number(__ENV.VUS || "1");
const iterations = Number(__ENV.ITERATIONS || "0");
const uploadTimeout = __ENV.UPLOAD_TIMEOUT || "10m";
const readChunkBytes = 4 * 1024 * 1024;

const manifest = JSON.parse(open("/fixtures/manifest.json"));
const pools = { photo: [], video: [] };
const duplicateUploads = new Counter("duplicate_uploads");

// k6/experimental/fs loads each file once and shares it between VUs, unlike
// open(), which copies the file into every VU.
(async function () {
  for (const fixture of manifest.files) {
    pools[fixture.kind].push({ fixture, file: await openFile(`/fixtures/${fixture.file}`) });
  }
})();

export const options = {
  scenarios: {
    upload: iterations > 0
      ? { executor: "shared-iterations", vus, iterations, maxDuration: __ENV.MAX_DURATION || "6h" }
      : { executor: "constant-vus", vus, duration: __ENV.DURATION || "30s" },
  },
  thresholds: { http_req_failed: ["rate<0.05"] },
};

const crcTable = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

const ascii = (text) => Uint8Array.from(Array.from(text, (char) => char.charCodeAt(0)));
const uint32 = (value) => [value >>> 24, (value >>> 16) & 0xff, (value >>> 8) & 0xff, value & 0xff];
const hex = (buffer) => Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");

// Each upload gets a unique, format-valid marker so Immich's checksum
// deduplication never short-circuits processing.
const markers = {
  // Top-level `free` box, which MP4 parsers skip.
  mp4: (id) => Uint8Array.from([...uint32(24), ...ascii("free"), ...new Uint8Array(randomBytes(16))]),
  // tEXt chunk, inserted before IEND.
  png: (id) => {
    const body = ascii(`tEXtk6\0${id}`);
    return Uint8Array.from([...uint32(body.length - 4), ...body, ...uint32(crc32(body))]);
  },
  // COM segment, inserted after SOI.
  jpg: (id) => {
    const payload = ascii(`k6 ${id}`);
    const length = payload.length + 2;
    return Uint8Array.from([0xff, 0xfe, length >> 8, length & 0xff, ...payload]);
  },
};

let chunk;

async function readUnique(file, fixture) {
  const marker = markers[fixture.format](hex(randomBytes(16)));
  const size = fixture.bytes;
  const data = new Uint8Array(size + marker.length);
  chunk = chunk || new Uint8Array(readChunkBytes);

  await file.seek(0, SeekMode.Start);
  let offset = 0;
  while (offset < size) {
    const read = await file.read(chunk);
    if (read === null) break;
    data.set(chunk.subarray(0, Math.min(read, size - offset)), offset);
    offset += read;
  }
  if (offset !== size) throw new Error(`${fixture.file}: read ${offset} of ${size} bytes`);

  if (fixture.format === "mp4") {
    data.set(marker, size);
  } else if (fixture.format === "png") {
    data.copyWithin(size - 12 + marker.length, size - 12, size);
    data.set(marker, size - 12);
  } else {
    data.copyWithin(2 + marker.length, 2, size);
    data.set(marker, 2);
  }
  return data;
}

function uploadStatus(response) {
  try {
    return response.json("status");
  } catch (error) {
    return undefined;
  }
}

export default async function () {
  const usePhoto = pools.photo.length > 0 && (pools.video.length === 0 || Math.random() < photoRatio);
  const pool = usePhoto ? pools.photo : pools.video;
  const { fixture, file } = pool[Math.floor(Math.random() * pool.length)];
  const data = await readUnique(file, fixture);
  const tags = {
    kind: fixture.kind,
    size_level: fixture.size_level,
    resolution: fixture.resolution,
    format: fixture.format,
  };

  const response = http.post(
    `${endpoint}/api/assets`,
    {
      assetData: http.file(data.buffer, fixture.file, fixture.content_type),
      deviceAssetId: `${__VU}-${__ITER}-${fixture.id}`,
      deviceId: "k6",
      fileCreatedAt: new Date().toISOString(),
      fileModifiedAt: new Date().toISOString(),
      isFavorite: "false",
      isArchived: "false",
    },
    { headers: { "x-api-key": apiKey }, timeout: uploadTimeout, tags },
  );

  const status = uploadStatus(response);
  check(response, {
    "upload accepted": (result) => result.status >= 200 && result.status < 300,
    "asset created (not duplicate)": () => status === "created",
  }, tags);
  if (status === "duplicate") duplicateUploads.add(1, tags);
  sleep(1);
}

export function handleSummary(data) {
  return { "/results/k6-summary.json": JSON.stringify(data, null, 2) };
}
