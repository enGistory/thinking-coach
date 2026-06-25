import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";

export default [
  {
    ignores: ["dist", "dev-dist", "node_modules", "coverage"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  {
    files: ["**/*.{js,ts,vue}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        AbortController: "readonly",
        AbortSignal: "readonly",
        Blob: "readonly",
        File: "readonly",
        FormData: "readonly",
        BlobEvent: "readonly",
        MediaRecorder: "readonly",
        MediaStream: "readonly",
        Response: "readonly",
        URL: "readonly",
        console: "readonly",
        crypto: "readonly",
        fetch: "readonly",
        indexedDB: "readonly",
        localStorage: "readonly",
        navigator: "readonly",
        process: "readonly",
        sessionStorage: "readonly",
        window: "readonly",
      },
    },
  },
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
];
