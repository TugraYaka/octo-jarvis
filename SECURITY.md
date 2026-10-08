# Security policy

## Supported versions

Only the latest release receives security fixes. Please update (`jarvis` installs from the newest release, or run the one-line installer again) before reporting.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

Use GitHub's private reporting instead: open the **Security** tab of this repository and choose **Report a vulnerability**. Include what you found, the steps to reproduce it and the version (`jarvis --version`).

You will get a first answer as soon as possible; this is a personal project, so there is no guaranteed response time. Fixes are released as a new version and credited to you if you wish.

## What JARVIS stores and sends

- Your Gemini API key is stored only on your computer, in `config.json` in the JARVIS data folder (readable only by you). It is sent only to Google's Gemini API.
- JARVIS never asks for passwords or payment details and refuses to type into password fields in its browser.
- Downloads (speech model, browser, TTS server) happen only after you agree, and installer packages are verified with a SHA-256 checksum.
- Web pages and search results are treated as untrusted text and are never followed as instructions.
- Plugins from a personal repository run with your permissions, so only add repositories you trust.
