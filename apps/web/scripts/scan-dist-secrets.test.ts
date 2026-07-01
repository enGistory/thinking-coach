import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

const script = "scripts/scan-dist-secrets.mjs";

describe("scan-dist-secrets", () => {
  it("reports secret value matches without printing the value", () => {
    const dir = mkdtempSync(join(tmpdir(), "web-dist-secret-scan-"));
    const secretValue = "prod-jwt-secret-value-that-must-not-print";
    try {
      writeFileSync(join(dir, "app.js"), `window.__leak = ${JSON.stringify(secretValue)};`);

      const result = spawnSync("node", [script], {
        cwd: new URL("..", import.meta.url),
        env: {
          ...process.env,
          WEB_DIST_SCAN_DIR: dir,
          JWT_SECRET: secretValue,
        },
        encoding: "utf-8",
      });

      const output = `${result.stdout}${result.stderr}`;
      expect(result.status).toBe(1);
      expect(output).toContain("contains value from JWT_SECRET");
      expect(output).not.toContain(secretValue);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("passes when no forbidden server-side material is present", () => {
    const dir = mkdtempSync(join(tmpdir(), "web-dist-secret-scan-"));
    try {
      writeFileSync(join(dir, "app.js"), "window.__app = 'ok';");

      const result = spawnSync("node", [script], {
        cwd: new URL("..", import.meta.url),
        env: {
          ...process.env,
          WEB_DIST_SCAN_DIR: dir,
          JWT_SECRET: "prod-jwt-secret-value-that-is-absent",
        },
        encoding: "utf-8",
      });

      expect(result.status).toBe(0);
      expect(result.stdout).toContain("web dist secret scan passed");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it.each([
    {
      label: "Aliyun OSS signed URL",
      expected: "contains Aliyun OSS signed URL marker",
      signedUrl:
        "https://private-bucket.oss-cn.example.com/audio.wav?OSSAccessKeyId=secret-key" +
        "&Expires=1893456000&Signature=secret-signature",
      secretFragment: "secret-signature",
    },
    {
      label: "Aliyun OSS v4 signed URL",
      expected: "contains Aliyun OSS v4 signed URL marker",
      signedUrl:
        "https://private-bucket.oss-cn.example.com/audio.wav?x-oss-signature-version=OSS4-HMAC-SHA256" +
        "&x-oss-signature=secret-v4-signature",
      secretFragment: "secret-v4-signature",
    },
    {
      label: "S3-compatible signed URL",
      expected: "contains S3-compatible signed URL marker",
      signedUrl:
        "https://private-bucket.s3.example.com/audio.wav?X-Amz-Algorithm=AWS4-HMAC-SHA256" +
        "&X-Amz-Signature=secret-s3-signature",
      secretFragment: "secret-s3-signature",
    },
  ])("reports $label markers without printing the URL", ({ expected, signedUrl, secretFragment }) => {
    const dir = mkdtempSync(join(tmpdir(), "web-dist-secret-scan-"));
    try {
      writeFileSync(join(dir, "asset.js"), `window.__audio = ${JSON.stringify(signedUrl)};`);

      const result = spawnSync("node", [script], {
        cwd: new URL("..", import.meta.url),
        env: {
          ...process.env,
          WEB_DIST_SCAN_DIR: dir,
        },
        encoding: "utf-8",
      });

      const output = `${result.stdout}${result.stderr}`;
      expect(result.status).toBe(1);
      expect(output).toContain(expected);
      expect(output).not.toContain(signedUrl);
      expect(output).not.toContain(secretFragment);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
