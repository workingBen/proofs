// Launch Playwright's Chromium for the --smoke check without downloading a browser.
// Order: PROOFS_BROWSER_CHANNEL if set and not "auto" (one launch); else the bundled browser, and
// when that is not installed, the installed Google Chrome (channel "chrome").
// Every launch carries the flag that stops Chrome on macOS from copying its whole
// app bundle into the temp folder.
const CHROME_ARGS = ["--disable-features=MacAppCodeSignClone"];
const HOW_TO =
  "Install Google Chrome, or point PROOFS_BROWSER_CHANNEL at another installed channel. " +
  "No browser download is needed: npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1";

async function launchChromium(chromium, env) {
  const channel = env && env.PROOFS_BROWSER_CHANNEL;
  if (channel && channel.trim() && channel.trim() !== "auto") return chromium.launch({ channel: channel.trim(), args: CHROME_ARGS });
  try {
    return await chromium.launch({ args: CHROME_ARGS });
  } catch (first) {
    if (!/Executable doesn't exist/.test(String(first && first.message))) throw first;
    try {
      return await chromium.launch({ channel: "chrome", args: CHROME_ARGS });
    } catch (second) {
      throw new Error(
        "Could not start a browser.\nBundled browser: " + first.message +
        "\nInstalled Chrome: " + second.message + "\n" + HOW_TO);
    }
  }
}

module.exports = { launchChromium, CHROME_ARGS, HOW_TO };
