import http from "k6/http";
import { check, sleep } from "k6";

const endpoint = __ENV.IMMICH_URL || "http://host.docker.internal:2283";
const apiKey = __ENV.IMMICH_API_KEY;
const photoRatio = Number(__ENV.PHOTO_RATIO || "0.5");
const photo = open("/fixtures/photo.jpg", "b");
const video = open("/fixtures/video.mp4", "b");

export const options = {
  vus: Number(__ENV.VUS || "1"),
  duration: __ENV.DURATION || "30s",
  thresholds: { http_req_failed: ["rate<0.05"] },
};

export default function () {
  const usePhoto = Math.random() < photoRatio;
  const body = http.file(usePhoto ? photo : video, usePhoto ? "photo.jpg" : "video.mp4");
  const response = http.post(
    `${endpoint}/api/assets`,
    {
      assetData: body,
      deviceAssetId: `${__VU}-${__ITER}-${usePhoto ? "photo" : "video"}`,
      deviceId: "k6",
      fileCreatedAt: new Date().toISOString(),
      fileModifiedAt: new Date().toISOString(),
      isFavorite: "false",
      isArchived: "false",
    },
    { headers: { "x-api-key": apiKey } },
  );

  check(response, { "upload accepted": (result) => result.status >= 200 && result.status < 300 });
  sleep(1);
}

export function handleSummary(data) {
  return { "/results/k6-summary.json": JSON.stringify(data, null, 2) };
}
