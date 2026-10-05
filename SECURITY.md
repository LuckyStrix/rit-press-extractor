# Security

## Intended deployment

The tool is designed to run on a computer you control, with your material
staying on that computer:

- `process`, `serve`, `truth`, `evaluate` and `debug` block their own outbound
  network access. Only `setup` downloads models.
- The phone capture server (`serve`) **listens on `127.0.0.1` only and has no
  login of its own.** It relies on [Tailscale](https://tailscale.com)
  (`tailscale serve`) to admit only your own devices.

**Do not expose the capture server to the public internet.** That includes
`tailscale funnel`, port forwarding, or a reverse proxy without authentication.
Anyone who could reach it could upload images and read the next item number.
If you need to host it for other people, put it behind real authentication
(for example an identity-aware proxy) and set `PRX_ALLOWED_USERS` to the
permitted Tailscale logins.

Uploads are size-limited (40 MB), must be valid JPEG images, never overwrite
existing files, and require a custom header so other websites can't post to the
page from a visitor's browser.

## Your data

- Photos, results and answer keys live in `data/`, which git ignores. Don't
  commit them and don't attach them to issues.
- When reporting a problem, share the **masked** output of `debug` or
  `evaluate --diff`, which hides the text.

## Reporting a vulnerability

Please report security problems privately through GitHub's
**Security → Report a vulnerability** on this repository rather than in a public
issue. Include steps to reproduce, and leave real documents out of the report.
