# Skills

A collection of [Agent Skills](https://docs.claude.com/en/docs/claude-code/skills) for Claude Code, packaged as a plugin marketplace so you can install just the ones you want.

## Install

Add this repo as a marketplace, then install any skill by name:

```
/plugin marketplace add rahulmohan126/skills
/plugin install prod-readiness@rahul-skills
```

Or from a terminal:

```bash
claude plugin marketplace add rahulmohan126/skills
claude plugin install prod-readiness@rahul-skills
```

Once installed, skills trigger on their own when a request matches. You can also ask for one by name.

## Available skills

| Skill | What it does |
|---|---|
| [prod-readiness](skills/prod-readiness/) | Checks whether a React app (Next.js, Astro, Vite) is ready for production. Runs ~50 launch, SEO and security checks against the source and, optionally, a live URL. Writes a pass/fail report with evidence and offers to apply fixes. |

<!-- Add a row here for each new skill. -->

## Repo layout

```
.
├── .claude-plugin/
│   └── marketplace.json     # one plugin entry per skill
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md         # frontmatter (name, description) + instructions
│       ├── references/      # docs the skill loads when it needs them
│       ├── scripts/         # helper scripts the skill runs
│       └── evals/           # test cases (claude plugin eval format)
```

## Adding a skill

1. Create `skills/<skill-name>/SKILL.md`. The folder name must match the `name` in its frontmatter.
2. Add an entry to `plugins` in `.claude-plugin/marketplace.json`:
   ```json
   {
     "name": "<skill-name>",
     "description": "One line on what it does.",
     "version": "0.1.0",
     "source": "./",
     "strict": false,
     "skills": ["./skills/<skill-name>"]
   }
   ```
3. Add a row to the table above.
4. Validate: `claude plugin validate .`

Each skill is its own plugin, so people can install them one at a time. To try a skill locally before publishing, symlink it into your personal skills folder:

```bash
ln -s "$PWD/skills/<skill-name>" ~/.claude/skills/<skill-name>
```

## Testing

Skills with an `evals/` folder can be tested with and without the skill. Run this from the skill's folder:

```bash
claude plugin eval . --allow-tools Write,Edit,Bash --scaffold
```

These are real, billed model runs.
