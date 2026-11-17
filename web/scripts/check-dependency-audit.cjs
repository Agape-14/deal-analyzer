const fs = require("node:fs");

const audit = JSON.parse(fs.readFileSync("dependency-audit.json", "utf8"));
const lock = JSON.parse(fs.readFileSync("package-lock.json", "utf8"));
if (audit.error || !audit.vulnerabilities) {
  throw new Error("The dependency audit did not return a vulnerability report.");
}

const blocking = Object.values(audit.vulnerabilities)
  .filter(item => item.severity === "high" || item.severity === "critical");

// Tailwind's build-time scanner uses fixed, repository-owned patterns.
// GHSA-fc5q-39xc-vjpf has no patched release. Allow this specific finding
// only while every affected installation is a development dependency.
const knownBuildOnly = blocking.length > 0 && blocking.every(item =>
  item.severity === "high" &&
  item.nodes.length > 0 && item.nodes.every(path => lock.packages[path]?.dev === true) &&
  item.via.every(cause => typeof cause === "string" ||
    (item.name === "picomatch" && cause.url === "https://github.com/advisories/GHSA-fc5q-39xc-vjpf"))
) && blocking.some(item => item.name === "picomatch");

if (knownBuildOnly) {
  console.log("Full audit recorded. Only the known build-time Picomatch advisory remains.");
} else if (blocking.length) {
  console.error("Blocking dependency advisories:", blocking.map(item => item.name).join(", "));
  process.exitCode = 1;
}