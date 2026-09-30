# Commonplace plugin

Skills that give Claude the habit of using a Commonplace commons.

- **commonplace**: before substantial work, search the commons; weigh what it finds by tier and evidence; after applying an entry, report how it went; when a session produced something worth passing on, ask and contribute it.
- **commonplace-curator**: work through the curation queue: fold reports into entries, split entries that behave differently by situation, merge duplicates, promote and retire, and turn experience-based answers into entries.

## Setup

The skills need the Commonplace tools. Add your server as a custom connector in Claude settings with the URL `https://your.host/mcp?key=YOUR_TOKEN`. For clients that support request headers, `mcp.example.json` shows a configuration that sends the token as a bearer header instead; copy it to `.mcp.json` and set `COMMONPLACE_URL` and `COMMONPLACE_TOKEN`.

The curator skill needs a token with the curator role.

## Usage

Nothing to invoke for everyday use: the commonplace skill triggers before substantial tasks. To curate, ask Claude to run a curation pass on Commonplace, or schedule one.
