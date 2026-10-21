# Security

`takecheck` reads media files with `ffmpeg`/`ffprobe` and parses YAML. Two areas matter:

1. **Malicious media.** `ffmpeg` is a large C codebase; a crafted file can crash it. `takecheck` runs
   `ffprobe` as a subprocess and treats its output as untrusted data, but it cannot make `ffmpeg`
   safe. Do not point it at files from untrusted sources in a privileged environment.
2. **Spec parsing.** `takes.yml` is parsed with `yaml.safe_load`; no object construction is allowed.
   Paths in a spec are used as given — do not run untrusted specs against a working directory you
   care about.

No network access, no telemetry, no credentials.

## Reporting

Open a private security advisory on GitHub (“Security” tab → “Report a vulnerability”). Please do not
open a public issue for a vulnerability. Expect an acknowledgement within a few days.
