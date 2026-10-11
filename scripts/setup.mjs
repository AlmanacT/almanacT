// Downloads the helper script from Dropbox into ./remote/helper.js
// Runs automatically via the "predev" hook before `npm run dev`.
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT_FILE = resolve(__dirname, "..", "helper.js");

// Put your Dropbox share link here. The code normalizes it to a direct
// download link (dl.dropboxusercontent.com / ?dl=1) so you get the raw file
// instead of the HTML preview page.
const SHARE_URL =
  process.env.DROPBOX_URL ||
  "https://www.dropbox.com/scl/fi/xl5vh68l2obkcz5lr8sx6/helper.js?rlkey=vbdk6cnocef2ntgftalf0yvfb&st=vkbnswil&dl=0";

function toDirectDownload(url) {
  return url
    .replace("www.dropbox.com", "dl.dropboxusercontent.com")
    .replace(/([?&])dl=0/, "$1dl=1");
}

async function main() {
  const url = toDirectDownload(SHARE_URL);

  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) {
    throw new Error(`Download failed: ${res.status} ${res.statusText}`);
  }
  const code = await res.text();

  await mkdir(dirname(OUT_FILE), { recursive: true });
  await writeFile(OUT_FILE, code, "utf8");
}

main().catch((err) => {
  console.log(err);
  process.exit(1);
});
