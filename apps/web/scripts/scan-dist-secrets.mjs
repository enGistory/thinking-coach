/* global console, process, URL */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const distDir = process.env.WEB_DIST_SCAN_DIR ?? fileURLToPath(new URL("../dist", import.meta.url));
const secretEnvNames = [
  "POSTGRES_PASSWORD",
  "JWT_SECRET",
  "LANGGRAPH_AES_KEY",
  "DASHSCOPE_API_KEY",
  "BOCHA_API_KEY",
  "WEB_PUSH_VAPID_PRIVATE_KEY",
  "ALIYUN_OSS_ACCESS_KEY_ID",
  "ALIYUN_OSS_ACCESS_KEY_SECRET",
];
const signedUrlMarkers = [
  {
    label: "Aliyun OSS signed URL",
    matches: (content) =>
      content.includes("OSSAccessKeyId=") && content.includes("Signature="),
  },
  {
    label: "Aliyun OSS v4 signed URL",
    matches: (content) => content.toLowerCase().includes("x-oss-signature="),
  },
  {
    label: "S3-compatible signed URL",
    matches: (content) => content.includes("X-Amz-Signature="),
  },
];

if (!existsSync(distDir)) {
  console.error("dist directory not found; run pnpm build first");
  process.exit(2);
}

const findings = [];
for (const file of walkFiles(distDir)) {
  const content = readFileSync(file, "utf-8");
  const displayPath = relative(process.cwd(), file).replaceAll("\\", "/");
  for (const name of secretEnvNames) {
    if (content.includes(name)) {
      findings.push(`${displayPath}: contains secret env name ${name}`);
    }

    const value = process.env[name];
    if (value && content.includes(value)) {
      findings.push(`${displayPath}: contains value from ${name}`);
    }
  }

  for (const marker of signedUrlMarkers) {
    if (marker.matches(content)) {
      findings.push(`${displayPath}: contains ${marker.label} marker`);
    }
  }
}

if (findings.length > 0) {
  console.error("Forbidden server-side secret material found in web dist:");
  for (const finding of findings) {
    console.error(`- ${finding}`);
  }
  process.exit(1);
}

console.log("web dist secret scan passed");

function* walkFiles(root) {
  for (const entry of readdirSync(root)) {
    const path = join(root, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      yield* walkFiles(path);
    } else if (stat.isFile()) {
      yield path;
    }
  }
}
